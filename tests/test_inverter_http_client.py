from solaxng.endpoints import POST_QUERY, POST_QUERY_XFF


def test_identical_descriptions_are_interned():
    """
    The copy-on-write builders hand back the same instance for the same
    request, so two descriptions can be compared by identity.
    """
    client = POST_QUERY.build("localhost", 80)

    assert client is POST_QUERY.build("localhost", 80)
    assert client is not POST_QUERY.build("localhost", 81)


def test_client_is_hashable_despite_carrying_a_dict():
    """
    A frozen dataclass derives __hash__ from its fields, which would raise
    on the headers dict, so the class hashes on identity instead.
    """
    client = POST_QUERY_XFF.build("localhost", 80)

    assert client.headers == {"X-Forwarded-For": "5.8.8.8"}
    assert hash(client) == id(client)
    assert len({client, POST_QUERY_XFF.build("localhost", 80)}) == 1
