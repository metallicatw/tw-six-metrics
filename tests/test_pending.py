

def test_the_saved_file_is_identified_by_its_title_not_a_menu_word():
    from twsix.ingest.pending import identify

    directors = (
        "<html><head><title>5439 高技 - 董事、監察人及內部關係人持股狀況統計"
        " - Goodinfo!台灣股市資訊網</title></head>"
        "<body><div class='menu'>股東持股分級 董監持股</div>"
        "<table><tr><td>董監持股比例</td></tr></table></body></html>"
    )
    got = identify(directors)
    assert got is not None and got.sheet == "董監持股"

    holders = (
        "<html><head><title>5439 高技 - 股東持股分級持股比例統計"
        " - Goodinfo!台灣股市資訊網</title></head>"
        "<body><div class='menu'>董監持股 股東持股分級</div>"
        "<table><tr><td>持股分級</td></tr></table></body></html>"
    )
    got = identify(holders)
    assert got is not None and got.sheet == "大戶持股"


def test_a_page_that_is_neither_is_not_forced_into_one():
    from twsix.ingest.pending import identify

    assert identify("<html><body>Forbidden</body></html>") is None
