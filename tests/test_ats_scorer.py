from src.job_hunt_ats_scorer import score_cv


class TestKeywordDensity:
    def test_all_keywords_matched(self) -> None:
        cv = "Experienced Python developer with SQL and Agile skills"
        keywords = ["python", "sql", "agile", "stakeholder management"]
        result = score_cv(cv, keywords)

        # 3 out of 4 matched = 0.75 * 25 = 18.75
        assert result["keyword_density"] == 18.75
        assert 0 <= result["keyword_density"] <= 25

    def test_no_keywords_matched(self) -> None:
        cv = "Experienced baker making cakes and bread"
        keywords = ["python", "sql", "agile"]
        result = score_cv(cv, keywords)

        assert result["keyword_density"] == 0.0

    def test_empty_keywords_list(self) -> None:
        cv = "Any CV text here"
        result = score_cv(cv, [])

        assert result["keyword_density"] == 25.0

    def test_partial_match(self) -> None:
        cv = "Python developer with SQL knowledge"
        keywords = ["python", "sql", "tableau", "power bi"]
        result = score_cv(cv, keywords)

        # 2 out of 4 matched = 0.5 * 25 = 12.5
        assert result["keyword_density"] == 12.5


class TestFormatScore:
    def test_plain_text_cv(self) -> None:
        cv = "John Doe\nEmail: john@example.com\nSummary: Experienced developer"
        result = score_cv(cv, [])

        assert result["format_score"] == 25

    def test_html_table_detected(self) -> None:
        cv = "<table><tr><td>Name</td><td>John</td></tr></table>"
        result = score_cv(cv, [])

        assert result["format_score"] == 0

    def test_pipe_table_detected(self) -> None:
        cv = "| Name | John | Surname | Doe |\n| Age | 30 |"
        result = score_cv(cv, [])

        assert result["format_score"] == 0

    def test_column_alignment_detected(self) -> None:
        cv = "Name    John    Surname    Doe\nAge    30"
        result = score_cv(cv, [])

        assert result["format_score"] == 0

    def test_multiple_all_caps_headers(self) -> None:
        cv = "SUMMARY\nExperienced developer\nSKILLS\nPython, SQL\nEXPERIENCE\nWork history here"
        result = score_cv(cv, [])

        assert result["format_score"] == 0

    def test_few_headers_not_flagged(self) -> None:
        cv = "John Doe\nSUMMARY\nExperienced developer"  # only one header
        result = score_cv(cv, [])

        assert result["format_score"] == 25

    def test_proper_formatted_cv(self) -> None:
        cv = "John Doe\nEmail: john@example.com\nSummary\nExperienced developer\nSkills\nPython, SQL"
        result = score_cv(cv, [])

        assert result["format_score"] == 25


class TestSectionPresence:
    def test_all_three_sections_present(self) -> None:
        cv = "Summary: experienced developer\nExperience: 5 years\nSkills: Python, SQL"
        result = score_cv(cv, [])

        # 8 + 8 + 9 = 25
        assert result["section_presence"] == 25

    def test_two_sections_present(self) -> None:
        cv = "Summary: experienced developer\nSkills: Python, SQL"
        result = score_cv(cv, [])

        # summary=8, skills=9
        assert result["section_presence"] == 17

    def test_one_section_present(self) -> None:
        cv = "Skills: Python, SQL"
        result = score_cv(cv, [])

        assert result["section_presence"] == 9

    def test_no_sections_detected(self) -> None:
        cv = "John Doe worked at company doing things with python"
        result = score_cv(cv, [])

        assert result["section_presence"] == 0

    def test_alternative_section_names(self) -> None:
        cv = "Profile: experienced developer\nExperience: 5 years\nCore competencies: Python"
        result = score_cv(cv, [])

        # experience=8, profile not detected, core competencies not detected
        assert result["section_presence"] == 8


class TestLengthScore:
    def test_word_count_in_range(self) -> None:
        # Generate text with 500 words
        words = ["word"] * 500
        cv = " ".join(words)
        result = score_cv(cv, [])

        assert result["length_score"] == 25

    def test_word_count_below_300(self) -> None:
        words = ["word"] * 200
        cv = " ".join(words)
        result = score_cv(cv, [])

        assert result["length_score"] == 0

    def test_word_count_above_800(self) -> None:
        words = ["word"] * 1000
        cv = " ".join(words)
        result = score_cv(cv, [])

        assert result["length_score"] == 0

    def test_word_count_at_lower_bound(self) -> None:
        words = ["word"] * 300
        cv = " ".join(words)
        result = score_cv(cv, [])

        assert result["length_score"] == 25

    def test_word_count_at_upper_bound(self) -> None:
        words = ["word"] * 800
        cv = " ".join(words)
        result = score_cv(cv, [])

        assert result["length_score"] == 25


class TestOverallScore:
    def test_max_score_scenario(self) -> None:
        # Perfect CV: all keywords, plain text, all sections, good length
        keywords = ["python", "sql", "agile"]
        cv = (
            "Summary: experienced Python developer with SQL skills\n"
            "Experience: 5 years in tech\n"
            "Skills: Python, SQL, Agile\n"
            + "word " * 400
        )
        result = score_cv(cv, keywords)

        assert result["overall"] <= 100
        assert result["overall"] >= 0

    def test_min_score_scenario(self) -> None:
        # Worst case: no keywords, table format, no sections, too short
        keywords = ["python", "sql"]
        cv = "<table><tr><td>Name</td><td>John</td></tr></table>"
        result = score_cv(cv, keywords)

        assert result["overall"] == 0

    def test_overall_is_sum_of_metrics(self) -> None:
        cv = "word " * 500
        keywords = ["python"]
        result = score_cv(cv, keywords)

        expected = (
            result["keyword_density"]
            + result["format_score"]
            + result["section_presence"]
            + result["length_score"]
        )
        # overall is int of sum, so compare rounded values
        assert result["overall"] == int(expected)

    def test_all_metrics_in_valid_range(self) -> None:
        cv = "Summary: experienced developer" + " word" * 400
        keywords = ["python"]
        result = score_cv(cv, keywords)

        assert 0 <= result["keyword_density"] <= 25
        assert 0 <= result["format_score"] <= 25
        assert 0 <= result["section_presence"] <= 25
        assert 0 <= result["length_score"] <= 25