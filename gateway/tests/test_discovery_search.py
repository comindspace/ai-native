import unittest

from support import install_dependency_stubs

install_dependency_stubs()

from gateway_mcp.tools.discovery import match_route_declarations

ITEMS = [
    {
        "name": "bitrix24.deals.list",
        "scope": "bitrix24:read",
        "description": "List Bitrix24 deals.",
        "keywords": ["битрикс", "сделки", "воронка"],
    },
    {
        "name": "bitrix24.leads.list",
        "scope": "bitrix24:read",
        "description": "List Bitrix24 leads.",
        "keywords": ["битрикс", "лиды"],
    },
    {
        "name": "yonote.documents.search",
        "scope": "yonote:read",
        "description": "Search Yonote documents.",
    },
]


class MatchRouteDeclarationsTests(unittest.TestCase):
    def names(self, query: str) -> list[str]:
        return [item["name"] for item in match_route_declarations(ITEMS, query)]

    def test_empty_query_returns_all_routes(self) -> None:
        expected = [
            "bitrix24.deals.list",
            "bitrix24.leads.list",
            "yonote.documents.search",
        ]
        self.assertEqual(self.names(""), expected)
        self.assertEqual(self.names("   "), expected)

    def test_single_token_keeps_substring_behaviour(self) -> None:
        self.assertEqual(self.names("yonote.documents.search"), ["yonote.documents.search"])
        self.assertEqual(self.names("bitrix24.deals.list"), ["bitrix24.deals.list"])

    def test_multiple_tokens_are_and_matched(self) -> None:
        self.assertEqual(self.names("bitrix24 deals"), ["bitrix24.deals.list"])
        self.assertEqual(self.names("bitrix24 unknown-word"), [])

    def test_russian_keywords_are_searchable(self) -> None:
        self.assertEqual(self.names("сделки"), ["bitrix24.deals.list"])
        self.assertEqual(self.names("лиды"), ["bitrix24.leads.list"])
        self.assertEqual(self.names("битрикс сделки"), ["bitrix24.deals.list"])


if __name__ == "__main__":
    unittest.main()
