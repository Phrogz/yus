import pydantic

import yus
from yus.sports import ultimate


class Throw(ultimate.Throw):
    """
    Throws in Indoor Ultimate track whether the disc hit the wall or net along the way.
    """

    hit_wall: bool = pydantic.Field(False, description="True if the disc hit the wall (caught or not).")
    hit_net: bool = pydantic.Field(False, description="True if the disc hit the netting (caught or not).")


terms: list[yus.Term] = list(ultimate.terms)
terms.extend(
    yus.Term(phrase=s.replace("_", " "), weight=0.2)
    for s in """
        wall glass net netting off_the_wall off_the_net
    """.split()
)
