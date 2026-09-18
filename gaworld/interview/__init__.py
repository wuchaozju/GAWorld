"""Group interview: ask one question set to many respondents at once.

The single-agent interview (``generative_city_sim.py interview``) answers
"what does resident #31 think?". This package answers the survey question:
*"what does this **population** think, and does the answer split by city, age
or industry?"* — which is a different artifact, not a loop around the old one:

* **Respondents are heterogeneous.** An individual resident and a
  :class:`~gaworld.group.cohort.Cohort` are both respondents here
  (:mod:`gaworld.interview.roster`). A cohort answers once for its whole
  group at cohort cost, which is what makes a 500-person town askable.
* **Respondents may live in different cities.** City bundles are
  self-contained and only one is config-selected at a time, so cross-city
  work is split into one child process per city
  (:mod:`gaworld.interview.__main__`) rather than by mutating global config
  under a thread pool.
* **Questions are typed.** ``open`` answers are prose; ``choice`` and
  ``boolean`` answers are parsed back into option labels and yes/no so they
  can be *counted* (:mod:`gaworld.interview.aggregate`). A survey you cannot
  tally is just a pile of transcripts.
* **A question may carry material** — an image or a URL
  (:mod:`gaworld.interview.attachments`).
* **A session is resumable.** Questions arrive in rounds and each respondent
  sees its own prior answers, so round 2 can say "回到你刚才提到的那点".

The interview never writes into agent memory. It is an observation of the
population, not an intervention on it: a run whose residents remember being
surveyed is a different experiment from one whose residents do not, and that
should never happen as a side effect of asking.
"""

from gaworld.interview.schema import (
    Answer,
    Attachment,
    Question,
    Respondent,
    SessionSpec,
    Transcript,
    normalize_questions,
    normalize_respondents,
    normalize_spec,
)

__all__ = [
    "Answer",
    "Attachment",
    "Question",
    "Respondent",
    "SessionSpec",
    "Transcript",
    "normalize_questions",
    "normalize_respondents",
    "normalize_spec",
]
