def test_reads_fixture(tmp_path):
    for filename in ("first.txt", "second.txt"):
        (tmp_path / filename).read_text()
