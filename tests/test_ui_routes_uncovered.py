"""Tests for untested ui_routes functions.

Coverage targets:
- build_parser (L82)
- main (L102) — NOTE: main is tightly coupled to server startup, mostly skipped
  but we test the parser it builds and basic argv handling
"""
from __future__ import annotations

import argparse
from pathlib import Path
from unittest import mock

import pytest

from src.ui_routes import build_parser


class TestBuildParser:
    """Tests for build_parser argument parser."""

    def test_build_parser_required_profile_arg(self) -> None:
        parser = build_parser()

        # Should require --profile
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_build_parser_accepts_profile(self, tmp_path: Path) -> None:
        parser = build_parser()
        profile_path = tmp_path / "profile.json"
        profile_path.write_text("{}")

        args = parser.parse_args(["--profile", str(profile_path)])

        assert args.profile == str(profile_path)

    def test_build_parser_default_state_root(self, tmp_path: Path) -> None:
        parser = build_parser()
        profile_path = tmp_path / "profile.json"
        profile_path.write_text("{}")

        args = parser.parse_args(["--profile", str(profile_path)])

        assert args.state_root == "data/state"

    def test_build_parser_custom_state_root(self, tmp_path: Path) -> None:
        parser = build_parser()
        profile_path = tmp_path / "profile.json"
        profile_path.write_text("{}")
        custom_state = tmp_path / "custom_state"

        args = parser.parse_args([
            "--profile", str(profile_path),
            "--state-root", str(custom_state),
        ])

        assert args.state_root == str(custom_state)

    def test_build_parser_default_report_dir(self, tmp_path: Path) -> None:
        parser = build_parser()
        profile_path = tmp_path / "profile.json"
        profile_path.write_text("{}")

        args = parser.parse_args(["--profile", str(profile_path)])

        assert args.report_dir == "output/reports"

    def test_build_parser_custom_report_dir(self, tmp_path: Path) -> None:
        parser = build_parser()
        profile_path = tmp_path / "profile.json"
        profile_path.write_text("{}")
        custom_reports = tmp_path / "custom_reports"

        args = parser.parse_args([
            "--profile", str(profile_path),
            "--report-dir", str(custom_reports),
        ])

        assert args.report_dir == str(custom_reports)

    def test_build_parser_default_host(self, tmp_path: Path) -> None:
        parser = build_parser()
        profile_path = tmp_path / "profile.json"
        profile_path.write_text("{}")

        args = parser.parse_args(["--profile", str(profile_path)])

        assert args.host == "127.0.0.1"

    def test_build_parser_rejects_non_loopback_host(self, tmp_path: Path) -> None:
        parser = build_parser()
        profile_path = tmp_path / "profile.json"
        profile_path.write_text("{}")

        with pytest.raises(SystemExit):
            parser.parse_args([
                "--profile", str(profile_path),
                "--host", "0.0.0.0",
            ])

    def test_build_parser_default_port(self, tmp_path: Path) -> None:
        parser = build_parser()
        profile_path = tmp_path / "profile.json"
        profile_path.write_text("{}")

        args = parser.parse_args(["--profile", str(profile_path)])

        assert args.port == 9000

    def test_build_parser_custom_port(self, tmp_path: Path) -> None:
        parser = build_parser()
        profile_path = tmp_path / "profile.json"
        profile_path.write_text("{}")

        args = parser.parse_args([
            "--profile", str(profile_path),
            "--port", "8080",
        ])

        assert args.port == 8080

    def test_build_parser_port_as_integer(self, tmp_path: Path) -> None:
        parser = build_parser()
        profile_path = tmp_path / "profile.json"
        profile_path.write_text("{}")

        args = parser.parse_args([
            "--profile", str(profile_path),
            "--port", "12345",
        ])

        # Port should be converted to int
        assert isinstance(args.port, int)
        assert args.port == 12345

    def test_build_parser_all_args_together(self, tmp_path: Path) -> None:
        parser = build_parser()
        profile = tmp_path / "profile.json"
        profile.write_text("{}")
        state_root = tmp_path / "state"
        report_dir = tmp_path / "reports"

        args = parser.parse_args([
            "--profile", str(profile),
            "--state-root", str(state_root),
            "--report-dir", str(report_dir),
            "--host", "localhost",
            "--port", "5000",
        ])

        assert args.profile == str(profile)
        assert args.state_root == str(state_root)
        assert args.report_dir == str(report_dir)
        assert args.host == "localhost"
        assert args.port == 5000

    def test_build_parser_invalid_port(self, tmp_path: Path) -> None:
        parser = build_parser()
        profile_path = tmp_path / "profile.json"
        profile_path.write_text("{}")

        with pytest.raises(SystemExit):
            parser.parse_args([
                "--profile", str(profile_path),
                "--port", "not-a-number",
            ])

    def test_build_parser_helps(self) -> None:
        parser = build_parser()

        # Parser should have description
        assert parser.description is not None
        assert "minimal" in parser.description.lower() or "evaluation" in parser.description.lower()

    def test_build_parser_profile_help_text(self) -> None:
        parser = build_parser()

        # Find the profile argument
        for action in parser._actions:
            if "--profile" in action.option_strings:
                assert action.help is not None
                assert "profile" in action.help.lower()
                assert action.required is True

    def test_build_parser_state_root_help_text(self) -> None:
        parser = build_parser()

        for action in parser._actions:
            if "--state-root" in action.option_strings:
                assert action.help is not None
                assert "state" in action.help.lower()

    def test_build_parser_port_help_text(self) -> None:
        parser = build_parser()

        for action in parser._actions:
            if "--port" in action.option_strings:
                assert action.help is not None
                assert "port" in action.help.lower()
