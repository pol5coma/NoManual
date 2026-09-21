"""Retrieval never leaves the product the user selected.

This is the difference between NoManual and pasting a manual into a chatbot: an
answer about a washing machine must not be built from the air conditioner's
pages. The rule is enforced by scope_to_product(), and it has two halves - the
manuals linked to the product, and the models a passage applies to - so both
are tested here.

Embeddings are deterministic vectors rather than calls to OpenAI: what is being
tested is the filter, not the embedding model.
"""

from conftest import link, make_chunk, make_manual, make_product, vector

from nomanual.searching.search import hybrid_search, lexical_search, query_texts


async def _two_products_with_chunks(session):
    """Two appliances, each with its own manual and one chunk of text."""
    oven = await make_product(session, brand="Balay", model="3HB4331X0")
    aircon = await make_product(session, brand="Haier", model="AS09FBAHRA")

    oven_manual = await make_manual(session, product=oven)
    aircon_manual = await make_manual(session, product=aircon)

    await make_chunk(
        session,
        oven_manual,
        content="To preheat the oven, press the function knob and set 200 degrees.",
        seed=1.0,
    )
    await make_chunk(
        session,
        aircon_manual,
        content="To preheat is not supported; clean the air filter every two weeks.",
        seed=1.0,
    )
    await session.commit()
    return oven, aircon


async def test_vector_search_only_returns_the_selected_product(session):
    oven, _ = await _two_products_with_chunks(session)

    hits = await query_texts(vector(1.0), product_id=oven.id)

    assert len(hits) == 1
    assert "preheat the oven" in hits[0].content


async def test_lexical_search_only_returns_the_selected_product(session):
    oven, _ = await _two_products_with_chunks(session)

    # "preheat" appears in both chunks, so an unscoped search would return two.
    hits = await lexical_search("preheat", vector(1.0), product_id=oven.id)

    assert len(hits) == 1
    assert "preheat the oven" in hits[0].content


async def test_without_a_product_every_manual_competes(session):
    await _two_products_with_chunks(session)

    hits = await lexical_search("preheat", vector(1.0), product_id=None)

    assert len(hits) == 2


async def test_hybrid_search_stays_inside_the_product(session):
    oven, _ = await _two_products_with_chunks(session)

    hits = await hybrid_search(
        "how do I preheat it", translated="how do I preheat it", product_id=oven.id
    )

    assert hits
    assert all("preheat the oven" in hit.content for hit in hits)


async def test_a_family_manual_can_serve_several_products(session):
    """One manual, two models: both must find it."""
    first = await make_product(session, model="AS09FBAHRA")
    second = await make_product(session, model="AS12FBAHRA")

    manual = await make_manual(session, product=first)
    await link(session, manual, second)
    await make_chunk(session, manual, content="Set the timer with the TIMER button.")
    await session.commit()

    for product in (first, second):
        hits = await lexical_search("timer", vector(1.0), product_id=product.id)
        assert len(hits) == 1


async def test_applies_to_excludes_a_passage_from_a_sibling_model(session):
    """A family manual states things that only hold for some of its models."""
    with_display = await make_product(session, model="AS18FDAHRA")
    without_display = await make_product(session, model="AS09FBAHRA")

    manual = await make_manual(session, product=with_display)
    await link(session, manual, without_display)

    # Applies to one model only.
    await make_chunk(
        session,
        manual,
        content="Models with a digital display show the room temperature.",
        applies_to=[with_display.id],
    )
    # applies_to NULL: covers every model in the manual.
    await make_chunk(
        session,
        manual,
        content="Clean the display area with a dry cloth.",
        ordinal=1,
    )
    await session.commit()

    for_display = await lexical_search(
        "display", vector(1.0), product_id=with_display.id
    )
    for_other = await lexical_search(
        "display", vector(1.0), product_id=without_display.id
    )

    assert len(for_display) == 2
    assert len(for_other) == 1
    assert "dry cloth" in for_other[0].content
