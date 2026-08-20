"""
We use copier to ask questions, e.g. on how to configure each product.

This gives a consistent style for the back-and-forth with the user.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, MutableMapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, TypeVar, cast

import questionary  # used by copier, we mimic
from copier import JSONSerializable, Phase, Worker
from copier._types import MISSING
from copier._user_data import AnswersMap, Question
from pydantic import ValidationError

try:
    # Recent copier versions (> 9.17.0) validate `Question.jinja_env` against
    # their own SandboxedEnvironment subclass, not the plain jinja2 one.
    from copier._jinja_ext import SandboxedEnvironment  # type: ignore[attr-defined]
except ImportError:  # pragma: no cover - older copier
    # The two ignores cover both cases: on old copier the import above is
    # unresolved, on new copier this fallback narrows the type.
    from jinja2.sandbox import SandboxedEnvironment  # type: ignore[assignment]

# -------------------------- From dict of questions -------------------------- #

T = TypeVar("T")
TD = TypeVar("TD", bound=Mapping[str, Any])

QuestionsDict = dict[str, dict[str, Any]]
QuestionsMapping = Mapping[str, dict[str, Any]]


@dataclass(frozen=True)
class PromptResponse(Generic[TD]):
    """
    Response for a questionary prompt.

    Can be typed to restrict the expected answers, e.g. TD -> ProductDetails.
    """

    answers_map: AnswersMap
    questions: QuestionsMapping

    @property
    def answers(self) -> TD:
        """Answers, including hidden and secret ones."""
        out: dict[str, Any] = {}
        for k, v in self.answers_map.combined.items():
            if str(k).startswith("_"):
                continue
            if str(k) not in self.questions:
                continue
            # match Copier’s “rememberable” constraint
            if not isinstance(k, JSONSerializable) or not isinstance(
                v, JSONSerializable
            ):
                continue
            out[str(k)] = v
        return cast(TD, out)

    @property
    def answers_to_remember(self) -> TD:
        """Answers that copier would remember (no secrets, when=true)."""
        out: dict[str, Any] = {}
        for k, v in self.answers.items():
            if k in self.hidden:  # when = False
                continue
            if str(k) in self.secret:
                continue
            out[str(k)] = v
        return cast(TD, out)

    @property
    def secret(self):
        """Answers (keys) that are secret."""
        return {k for k, v in self.questions.items() if v.get("secret")}

    @property
    def hidden(self):
        """Answers (keys) with when=false."""
        return self.answers_map.hidden

    def merge(self, other: PromptResponse[TD]) -> PromptResponse[TD]:
        """Return a new PromptResponse that merges `other`.

        Assumes (and does not check) that questions are not duplicated."""

        questions: dict[str, dict[str, Any]] = {}
        questions.update(deepcopy(self.questions))
        questions.update(deepcopy(other.questions))

        answers_map = deepcopy(self.answers_map)

        # Update answers_map (a dataclass) via its attributes
        for field_name in (
            "user",
            "init",
            "metadata",
            "last",
            "user_defaults",
            "external",
            "hidden",
        ):
            getattr(answers_map, field_name).update(
                getattr(other.answers_map, field_name)
            )

        return PromptResponse(answers_map=answers_map, questions=questions)

    def __str__(self) -> str:
        return f"Answers: {str(self.answers)}"


def prompt_like_copier(
    questions: QuestionsMapping,
    data: Mapping[str, Any] | None = None,
):
    """
    Reimplementation of the essential steps in Worker._ask(), but driven by an
    in-memory questions_data mapping (like Template.questions_data).

    Parameters
    ----------
    questions:
        Copier-like questions mapping.
    data:
        Pre-populated answers, like Copier's `data`. These are treated as
        initial answers (`answers.init`) and will be parsed/validated and used
        to skip prompting for corresponding questions.

    ```
    questions = {
        "project_name": {
            "type": "str",
            "help": "Human readable name",
            "default": "My App",
        },
        "license": {"type": "str", "choices": ["MIT", "Apache-2.0"], "default": "MIT"},
        "admin_password": {
            "type": "str",
            "secret": True,
            "help": "Used for first login",
            "placeholder" : "asdf",
            "default" : ""
        },
    }

    print(ask_questions_like_copier(questions))
    ```
    """

    with Phase.use(Phase.PROMPT):
        answers_map = _ask_questions_like_copier(questions, answers_data=data)
        return PromptResponse(questions=questions, answers_map=answers_map)


def _ask_questions_like_copier(
    questions_data: QuestionsMapping,
    answers_data: Mapping[str, Any] | None = None,
) -> AnswersMap:
    # some variables for consistency with copier
    init: MutableMapping[str, Any] = dict(answers_data or {})
    last: MutableMapping[str, Any] = {}
    defaults = False
    skip_answered = False

    # Minimal render context. Copier’s Worker._render_context() is much richer.
    context: dict[str, Any] = {
        **init,
        **last,
        "_copier_phase": Phase.current(),
        "_copier_conf": {
            # Keep a placeholder structure; some templates reference _copier_conf
            "defaults": defaults,
        },
    }

    answers = AnswersMap(init=init)
    jinja_env = _jinja_env_like_copier()

    # Mimic Worker._ask() loop
    for var_name, details in questions_data.items():
        q = Question(
            answers=answers,
            context=context,
            jinja_env=jinja_env,
            var_name=var_name,
            **details,
        )

        # 1) If last answer exists but cannot be parsed/validated, drop it
        if var_name in answers.last:
            try:
                parsed = q.parse_answer(answers.last[var_name])
                q.validate_answer(parsed)
            except Exception:
                del answers.last[var_name]

        # 2) "when" evaluation: not really needed.
        # We'll still respect it if present, because Question.get_when() is cheap
        # and matches Copier behavior.
        if not q.get_when():
            answers.hide(var_name)
            if var_name in answers.last:
                del answers.last[var_name]
            if q.get_default() is MISSING:
                continue

        # 3) If answer was provided via init data,
        # parse/validate and store as user answer
        if var_name in answers.init:
            parsed = q.parse_answer(answers.init[var_name])
            q.validate_answer(parsed)
            answers.user[var_name] = parsed
            # Update context so later questions can reference earlier answers
            context[var_name] = parsed
            continue

        # 4) If skip_answered and last contains it, skip prompting
        if skip_answered and var_name in answers.last:
            # Keep it in last; also reflect in context
            context[var_name] = answers.last[var_name]
            continue

        # 5) Ask interactively or take defaults
        if defaults:
            new_answer = q.get_default()
            if new_answer is MISSING:
                raise ValueError(f'Question "{var_name}" is required')
        else:
            # Use the same machinery as Copier: Question builds a questionary structure.
            structure = q.get_questionary_structure()
            try:
                # questionary returns {var_name: answer}
                result = questionary.unsafe_prompt(
                    [structure],
                    answers={var_name: q.get_default()},
                )
                new_answer = result[var_name]
            except KeyboardInterrupt as err:
                # Copier raises CopierAnswersInterrupt with more info;
                # you can import and raise that if you want identical semantics.
                raise err

        # 6) Store user answer
        try:
            # Copier stores raw answer; validation is done during parsing/validators in
            # Question but it's fine to validate again if you want stricter behavior
            parsed = q.parse_answer(new_answer)
            q.validate_answer(parsed)
        except ValidationError as e:
            # In Copier this would normally re-prompt (questionary validators).
            # Here we just raise, since we're keeping the loop simple.
            raise e

        answers.user[var_name] = parsed
        context[var_name] = parsed

    return answers


def _jinja_env_like_copier() -> SandboxedEnvironment:
    """Get Jinja Environment similar to the one copier uses.

    This is a simple workaround, since copier does not expose its jinja env.
    For now, we have to add the jinja filters manually. Add as needed.

    To get a list what copier ships by default:

    ```python
    from copier import Worker
    w = Worker(src_path=".", dst_path=".", quiet=True)
    env = w.jinja_env
    print("\n".join(sorted(env.filters.keys())))
    ```
    """
    env = SandboxedEnvironment(autoescape=False)

    def regex_replace(
        value: Any, pattern: str, replacement: str = "", count: int = 0
    ) -> str:
        s = "" if value is None else str(value)
        return re.sub(pattern, replacement, s, count=count)

    def expanduser(value: Any) -> str:
        """
        - macOS/Linux: "~" and "~user" typically work.
        - Windows: "~" expands to the current user's home; "~user" often cannot
          be resolved -> we fall back to the original string.
        """
        if value is None:
            return ""
        s = str(value)

        if not s.startswith("~"):
            return s

        try:
            return str(Path(s).expanduser())
        except Exception:
            return s

    env.filters["regex_replace"] = regex_replace
    env.filters["expanduser"] = expanduser
    return env


def prompt_single(help: str, type: type[T] | None = None, **kwargs) -> T:
    """
    Ask a single questions, directly returning the answered value.

    kwargs follow copiers convention, e.g.
    - `help` for question text
    - `type` for input type
    - `secret`
    - `default`
    """

    if type is not None:
        if type in (bool, int, float, str):
            kwargs["type"] = type.__name__
        elif isinstance(type, str):
            kwargs["type"] = type
        elif type is Path:
            kwargs["type"] = "str"
            if "default" in kwargs:
                kwargs["default"] = str(kwargs["default"])
            # TODO: add path logic via typer/click
        else:
            raise NotImplementedError

    res = prompt_like_copier({"temp": dict(help=help, **kwargs)}).answers["temp"]

    if type is Path:
        res = Path(res)
    elif type in (bool, int, float, str):
        res = type(res)  # type: ignore
    return res  # type: ignore # FIXME


# -------------------------- From existing yaml file ------------------------- #


def prompt_like_copier_from_template(src_path: str, **kwargs) -> PromptResponse:
    """
    Use copier Questionaire to get answers.

    Arguments
    ---------
    - src_path : str
        needs to contain a copier.yml

    ```python
    prompt_like_copier_from_template(
        src_path = "./template_product"
    )
    ```
    """

    class AnswerWorker(Worker):
        def get_answers(self):
            with Phase.use(Phase.PROMPT):
                self._ask()

        def __enter__(self) -> AnswerWorker:
            return self

    with AnswerWorker(src_path=src_path, **kwargs) as worker:
        worker.get_answers()
        answers = PromptResponse[Any](
            questions=worker.template.questions_data,
            answers_map=worker.answers,
        )
        return answers


# ---------------------------------- Helper ---------------------------------- #


def tree(dir_path: Path, prefix: str = ""):
    """A recursive generator, given a directory Path object
    will yield a visual tree structure line by line
    with each line prefixed by the same characters

    ```
    for line in tree(Path.home() / 'pyscratch'):
        print(line)
    ```

    https://stackoverflow.com/questions/9727673/list-directory-tree-structure-in-python
    """
    # prefix components:
    space = "    "
    branch = "│   "
    # pointers:
    tee = "├── "
    last = "└── "

    contents = list(dir_path.iterdir())
    # contents each get pointers that are ├── with a final └── :
    pointers = [tee] * (len(contents) - 1) + [last]
    for pointer, path in zip(pointers, contents):
        yield prefix + pointer + path.name
        if path.is_dir():  # extend the prefix and recurse:
            extension = branch if pointer == tee else space
            # i.e. space because last, └── , above so no more |
            yield from tree(path, prefix=prefix + extension)
