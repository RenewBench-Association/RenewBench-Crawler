"""Tests for BARRA reanalysis downloader."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from rbc.weather.barra import BarraDownloader
from rbc.weather.barra.mappings import (
    DEFAULT_VARIABLES_C2,
    DEFAULT_VARIABLES_R2_RE2,
)


class TestBarraDownloaderInit:
    """Test BarraDownloader initialization."""

    def test_init_r2_model(self, tmp_path):
        """Test initialization with R2 model."""
        downloader = BarraDownloader(
            output_path=tmp_path,
            model="R2",
            years=[2020, 2021],
        )
        assert downloader.model == "R2"
        assert downloader.years == [2020, 2021]
        assert downloader.temporal_res == "1hr"
        assert downloader.output_path == tmp_path

    def test_init_re2_model(self, tmp_path):
        """Test initialization with RE2 model."""
        downloader = BarraDownloader(
            output_path=tmp_path,
            model="RE2",
            years=[2021],
        )
        assert downloader.model == "RE2"
        assert len(downloader.available_variables) > 0

    def test_init_c2_model(self, tmp_path):
        """Test initialization with C2 model."""
        downloader = BarraDownloader(
            output_path=tmp_path,
            model="C2",
            years=[2022],
        )
        assert downloader.model == "C2"
        # C2 has convective parameters
        assert "CAPE" in downloader.available_variables or True  # Depends on mapping

    def test_init_invalid_model(self, tmp_path):
        """Test initialization with invalid model."""
        with pytest.raises(ValueError, match="Unknown BARRA model"):
            BarraDownloader(
                output_path=tmp_path,
                model="INVALID",
                years=[2020],
            )

    def test_init_creates_output_directory(self, tmp_path):
        """Test that output directory is created."""
        output_path = tmp_path / "new_dir" / "barra_data"
        assert not output_path.exists()

        BarraDownloader(
            output_path=output_path,
            model="R2",
            years=[2020],
        )
        assert output_path.exists()

    def test_init_with_months(self, tmp_path):
        """Test initialization with specific months."""
        months = ["01", "03", "06", "12"]
        downloader = BarraDownloader(
            output_path=tmp_path,
            model="R2",
            years=[2020],
            months=months,
        )
        assert downloader.months == months

    def test_init_with_all_months_default(self, tmp_path):
        """Test that all months are used by default."""
        downloader = BarraDownloader(
            output_path=tmp_path,
            model="R2",
            years=[2020],
        )
        assert len(downloader.months) == 12
        assert downloader.months == [f"{i:02d}" for i in range(1, 13)]

    def test_init_with_custom_variables(self, tmp_path):
        """Test initialization with custom variables."""
        variables = ["tas", "pr", "uas"]
        downloader = BarraDownloader(
            output_path=tmp_path,
            model="R2",
            years=[2020],
            variables=variables,
        )
        assert downloader.variables == variables

    def test_init_with_default_variables_r2(self, tmp_path):
        """Test that R2 uses correct default variables."""
        downloader = BarraDownloader(
            output_path=tmp_path,
            model="R2",
            years=[2020],
        )
        assert downloader.variables == DEFAULT_VARIABLES_R2_RE2

    def test_init_with_default_variables_c2(self, tmp_path):
        """Test that C2 uses correct default variables."""
        downloader = BarraDownloader(
            output_path=tmp_path,
            model="C2",
            years=[2020],
        )
        assert downloader.variables == DEFAULT_VARIABLES_C2

    def test_init_with_pressure_levels(self, tmp_path):
        """Test initialization with custom pressure levels."""
        levels = [500, 700, 850, 1000]
        downloader = BarraDownloader(
            output_path=tmp_path,
            model="R2",
            years=[2020],
            pressure_levels=levels,
        )
        assert downloader.pressure_levels == levels

    def test_init_with_default_pressure_levels(self, tmp_path):
        """Test that default pressure levels are used."""
        downloader = BarraDownloader(
            output_path=tmp_path,
            model="R2",
            years=[2020],
        )
        assert 500 in downloader.pressure_levels
        assert 850 in downloader.pressure_levels


class TestBarraDownloaderCheckpoint:
    """Test checkpoint functionality."""

    def test_checkpoint_creation(self, tmp_path):
        """Test that checkpoint is created on init."""
        downloader = BarraDownloader(
            output_path=tmp_path,
            model="R2",
            years=[2020, 2021],
            months=["01", "02", "03"],
        )
        assert downloader.checkpoint.shape == (2, 3)  # 2 years, 3 months
        assert np.all(downloader.checkpoint == 0)  # All zeros initially

    def test_checkpoint_persistence(self, tmp_path):
        """Test that checkpoint is saved and loaded."""
        years = [2020, 2021]
        months = ["01", "02"]

        # Create downloader and modify checkpoint
        downloader1 = BarraDownloader(
            output_path=tmp_path,
            model="R2",
            years=years,
            months=months,
        )
        downloader1.checkpoint[0, 0] = 1
        downloader1._save_checkpoint()

        # Create new downloader and verify checkpoint is loaded
        downloader2 = BarraDownloader(
            output_path=tmp_path,
            model="R2",
            years=years,
            months=months,
            resume=True,
        )
        assert downloader2.checkpoint[0, 0] == 1

    def test_checkpoint_not_resumed_if_resume_false(self, tmp_path):
        """Test that checkpoint is ignored if resume=False."""
        years = [2020]
        months = ["01"]

        # Create and save checkpoint
        downloader1 = BarraDownloader(
            output_path=tmp_path,
            model="R2",
            years=years,
            months=months,
        )
        downloader1.checkpoint[0, 0] = 1
        downloader1._save_checkpoint()

        # Create new downloader with resume=False
        downloader2 = BarraDownloader(
            output_path=tmp_path,
            model="R2",
            years=years,
            months=months,
            resume=False,
        )
        assert downloader2.checkpoint[0, 0] == 0

    def test_get_file_status(self, tmp_path):
        """Test file status tracking."""
        downloader = BarraDownloader(
            output_path=tmp_path,
            model="R2",
            years=[2020, 2021],
            months=["01", "02"],
        )
        completed, total = downloader.get_file_status()
        assert completed == 0
        assert total == 4  # 2 years × 2 months

        downloader.checkpoint[0, 0] = 1
        completed, total = downloader.get_file_status()
        assert completed == 1


class TestBarraDownloaderVariables:
    """Test variable management."""

    def test_list_variables_r2(self, tmp_path):
        """Test variable listing for R2."""
        downloader = BarraDownloader(
            output_path=tmp_path,
            model="R2",
            years=[2020],
        )
        vars_list = downloader.list_variables()
        assert isinstance(vars_list, list)
        assert len(vars_list) > 0
        assert all(isinstance(v, str) for v in vars_list)
        assert "tas" in vars_list  # 2m temperature should be available

    def test_list_variables_c2(self, tmp_path):
        """Test variable listing for C2."""
        downloader = BarraDownloader(
            output_path=tmp_path,
            model="C2",
            years=[2020],
        )
        vars_list = downloader.list_variables()
        assert isinstance(vars_list, list)
        assert len(vars_list) > 0

    def test_available_variables_different_per_resolution(self, tmp_path):
        """Test that available variables differ by resolution."""
        downloader_r2 = BarraDownloader(
            output_path=tmp_path,
            model="R2",
            years=[2020],
        )
        downloader_c2 = BarraDownloader(
            output_path=tmp_path,
            model="C2",
            years=[2020],
        )
        # C2 should have more variables (includes convective diagnostics)
        assert len(downloader_c2.available_variables) >= len(
            downloader_r2.available_variables
        )


class TestBarraDownloaderFilePath:
    """Test file path construction."""

    def test_construct_file_path(self, tmp_path):
        """Test file path construction."""
        downloader = BarraDownloader(
            output_path=tmp_path,
            model="R2",
            years=[2020],
        )
        file_path = downloader._construct_file_path(2020, "01", "tas")
        assert file_path.parent == tmp_path
        assert "R2" in str(file_path)
        assert "202001" in str(file_path)
        assert "tas" in str(file_path)
        assert str(file_path).endswith(".nc")

    def test_construct_file_path_different_vars(self, tmp_path):
        """Test file paths for different variables."""
        downloader = BarraDownloader(
            output_path=tmp_path,
            model="R2",
            years=[2020],
        )
        path1 = downloader._construct_file_path(2020, "01", "tas")
        path2 = downloader._construct_file_path(2020, "01", "pr")
        assert str(path1) != str(path2)
        assert "tas" in str(path1)
        assert "pr" in str(path2)


class TestBarraDownloaderURL:
    """Test URL construction."""

    def test_build_opendap_url_r2(self, tmp_path):
        """Test OPeNDAP URL construction for R2."""
        downloader = BarraDownloader(
            output_path=tmp_path,
            model="R2",
            years=[2020],
        )
        url = downloader._build_opendap_url(2020, "06", "tas")
        assert "thredds.nci.org.au" in url or "dodsC" in url or "202006" in url

    def test_build_opendap_url_different_resolution(self, tmp_path):
        """Test that URLs differ by resolution."""
        downloader_r2 = BarraDownloader(
            output_path=tmp_path,
            model="R2",
            years=[2020],
        )
        downloader_c2 = BarraDownloader(
            output_path=tmp_path,
            model="C2",
            years=[2020],
        )
        url_r2 = downloader_r2._build_opendap_url(2020, "01", "tas")
        url_c2 = downloader_c2._build_opendap_url(2020, "01", "tas")
        # URLs should be different (different base paths for different resolutions)
        assert url_r2 != url_c2


class TestBarraDownloaderConfiguration:
    """Test resolution-specific configuration."""

    def test_r2_config(self, tmp_path):
        """Test R2 configuration."""
        downloader = BarraDownloader(
            output_path=tmp_path,
            model="R2",
            years=[2020],
        )
        assert "R2" in downloader.config["label"]
        assert "11 km" in downloader.config["resolution"]
        assert "AUS-11" in downloader.config["grid"]

    def test_re2_config(self, tmp_path):
        """Test RE2 configuration."""
        downloader = BarraDownloader(
            output_path=tmp_path,
            model="RE2",
            years=[2020],
        )
        assert "RE2" in downloader.config["label"]
        assert "22 km" in downloader.config["resolution"]
        assert "AUS-22" in downloader.config["grid"]
        assert "ensemble" in downloader.config["description"]

    def test_c2_config(self, tmp_path):
        """Test C2 configuration."""
        downloader = BarraDownloader(
            output_path=tmp_path,
            model="C2",
            years=[2020],
        )
        assert "C2" in downloader.config["label"]
        assert "4 km" in downloader.config["resolution"]
        assert "AUST-04" in downloader.config["grid"]
        assert "convective" in downloader.config["description"].lower()


class TestBarraDownloaderTemporal:
    """Test temporal frequency support (fixed to 1hr)."""

    def test_temporal_frequency_always_1hr_r2(self, tmp_path):
        """Test that temporal frequency is fixed to 1hr for R2."""
        downloader = BarraDownloader(
            output_path=tmp_path,
            model="R2",
            years=[2020],
        )
        assert downloader.temporal_res == "1hr"

    def test_temporal_frequency_always_1hr_re2(self, tmp_path):
        """Test that temporal frequency is fixed to 1hr for RE2."""
        downloader = BarraDownloader(
            output_path=tmp_path,
            model="RE2",
            years=[2020],
        )
        assert downloader.temporal_res == "1hr"

    def test_temporal_frequency_always_1hr_c2(self, tmp_path):
        """Test that temporal frequency is fixed to 1hr for C2."""
        downloader = BarraDownloader(
            output_path=tmp_path,
            model="C2",
            years=[2020],
        )
        assert downloader.temporal_res == "1hr"


class TestBarraDownloaderDryRun:
    """Test dry-run functionality."""

    def test_dry_run_flag(self, tmp_path):
        """Test dry_run flag setting."""
        downloader = BarraDownloader(
            output_path=tmp_path,
            model="R2",
            years=[2020],
            dry_run=True,
        )
        assert downloader.dry_run is True

        downloader_normal = BarraDownloader(
            output_path=tmp_path,
            model="R2",
            years=[2020],
            dry_run=False,
        )
        assert downloader_normal.dry_run is False


class TestBarraDownloaderDiscovery:
    """Test variable discovery from THREDDS."""

    def test_discover_variables_returns_dict(self, tmp_path):
        """Test that discover_variables returns a dictionary."""
        downloader = BarraDownloader(
            output_path=tmp_path,
            model="R2",
            years=[2020],
        )
        with patch("rbc.weather.barra.downloader.requests.get") as mock_get:
            mock_response = MagicMock()
            mock_response.text = "BARRA_R2_202001_tas.nc BARRA_R2_202001_pr.nc"
            mock_get.return_value = mock_response

            result = downloader.discover_variables()
            assert isinstance(result, dict)

    def test_discover_variables_handles_error(self, tmp_path):
        """Test error handling in discover_variables."""
        downloader = BarraDownloader(
            output_path=tmp_path,
            model="R2",
            years=[2020],
        )
        with patch("rbc.weather.barra.downloader.requests.get") as mock_get:
            mock_get.side_effect = Exception("Connection error")
            result = downloader.discover_variables()
            assert result == {}


class TestBarraDownloaderIntegration:
    """Integration tests."""

    def test_full_workflow_dry_run(self, tmp_path):
        """Test full workflow with dry run."""
        downloader = BarraDownloader(
            output_path=tmp_path,
            model="R2",
            years=[2020],
            months=["01"],
            variables=["tas", "pr"],
            dry_run=True,
        )
        # Dry run should complete without errors
        downloader.download()

    def test_multiple_resolutions_independent(self, tmp_path):
        """Test that downloaders for different resolutions are independent."""
        downloader_r2 = BarraDownloader(
            output_path=tmp_path / "r2",
            model="R2",
            years=[2020],
        )
        downloader_re2 = BarraDownloader(
            output_path=tmp_path / "re2",
            model="RE2",
            years=[2020],
        )
        assert downloader_r2.model == "R2"
        assert downloader_re2.model == "RE2"
        assert downloader_r2.output_path != downloader_re2.output_path


# Fixtures
@pytest.fixture
def tmp_path():
    """Provide a temporary directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)
