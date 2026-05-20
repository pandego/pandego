import unittest

from scripts.update_oss_section import build_section


class BuildSectionTests(unittest.TestCase):
    def test_groups_external_merged_prs_by_project_with_filtered_links_ordered_by_stars(self):
        prs = [
            {
                "title": "fix one",
                "html_url": "https://github.com/acme/widgets/pull/12",
                "number": 12,
                "repository_url": "https://api.github.com/repos/acme/widgets",
                "repository_stars": 10,
            },
            {
                "title": "fix two",
                "html_url": "https://github.com/acme/widgets/pull/13",
                "number": 13,
                "repository_url": "https://api.github.com/repos/acme/widgets",
                "repository_stars": 10,
            },
            {
                "title": "fix other",
                "html_url": "https://github.com/other/tooling/pull/4",
                "number": 4,
                "repository_url": "https://api.github.com/repos/other/tooling",
                "repository_stars": 900,
            },
        ]

        section = build_section(prs, updated_at="2026-04-30 10:00 UTC")

        self.assertIn("**Projects contributed to:**", section)
        self.assertIn("[acme/widgets](https://github.com/acme/widgets/pulls?q=is%3Apr+is%3Amerged+author%3Apandego) (10 stars)", section)
        self.assertIn("[other/tooling](https://github.com/other/tooling/pulls?q=is%3Apr+is%3Amerged+author%3Apandego) (900 stars)", section)
        self.assertNotIn("merged PRs,", section)
        self.assertLess(section.index("other/tooling"), section.index("acme/widgets"))
        self.assertIn("**Latest merged PRs:**", section)
        self.assertIn("[acme/widgets#12](https://github.com/acme/widgets/pull/12) - fix one", section)
        self.assertIn("_Last updated: 2026-04-30 10:00 UTC_", section)

    def test_filters_owned_repos_out_of_project_and_recent_lists(self):
        section = build_section(
            [
                {
                    "title": "own profile update",
                    "html_url": "https://github.com/pandego/pandego/pull/1",
                    "number": 1,
                    "repository_url": "https://api.github.com/repos/pandego/pandego",
                }
            ],
            updated_at="2026-04-30 10:00 UTC",
        )

        self.assertIn("- _No external merged PR projects found yet._", section)
        self.assertIn("- _No recent external merged PRs found yet._", section)
        self.assertNotIn("pandego/pandego#1", section)

    def test_includes_bot_landed_pytorch_prs_with_closed_merged_label_filter(self):
        section = build_section(
            [
                {
                    "title": "[inductor] Realize conv bias input before freezing layout",
                    "html_url": "https://github.com/pytorch/pytorch/pull/181363",
                    "number": 181363,
                    "repository_url": "https://api.github.com/repos/pytorch/pytorch",
                    "repository_stars": 921000,
                    "acceptance": "bot_landed",
                }
            ],
            updated_at="2026-05-20 10:00 UTC",
        )

        self.assertIn(
            "[pytorch/pytorch](https://github.com/pytorch/pytorch/pulls?q=is%3Apr+is%3Aclosed+label%3AMerged+author%3Apandego) (921,000 stars)",
            section,
        )
        self.assertIn(
            "[pytorch/pytorch#181363](https://github.com/pytorch/pytorch/pull/181363) - [inductor] Realize conv bias input before freezing layout",
            section,
        )


if __name__ == "__main__":
    unittest.main()
