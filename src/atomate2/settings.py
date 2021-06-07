"""Settings for atomate2."""

from pathlib import Path
from typing import Optional, Tuple, Union

from pydantic import BaseSettings, Field, root_validator

DEFAULT_CONFIG_FILE_PATH = str(Path.home() / ".atomate.json")


class Settings(BaseSettings):
    """
    Settings for atomate2.

    The default way to modify these is to modify ~/.atomate.yaml. Alternatively,
    the environment variable ATOMATE_CONFIG_FILE can be set to point to a yaml file with
    atomate2 settings.

    Lastly, the variables can be modified directly though environment variables by
    using the "ATOMATE" prefix. E..g., ATOMATE_SCRATCH_DIR = path/to/scratch.
    """

    CONFIG_FILE: str = Field(
        DEFAULT_CONFIG_FILE_PATH, description="File to load alternative defaults from"
    )

    # general settings
    SCRATCH_DIR: str = Field(
        ">>SCRATCH_DIR<<", description="Path to scratch directory (supports env_check)"
    )

    # VASP specific settings
    VASP_CMD: str = Field(
        "vasp_std", description="Command to run standard version of VASP"
    )
    VASP_GAMMA_CMD: str = Field(
        "vasp_gam", description="Command to run gamma only version of VASP"
    )
    VASP_NCL_CMD: str = Field(
        "vasp_ncl", description="Command to run ncl version of VASP"
    )
    VASP_VDW_KERNEL_DIRR: str = Field(
        ">>vdw_kernel_dir<<", description="Path to VDW VASP kernel"
    )
    VASP_ADD_NAMEFILE: bool = Field(
        True, description="Whether vasp.powerups.add_common_powerups adds a namefile"
    )
    VASP_ADD_SMALLGAP_KPOINT_MULTIPLY: bool = Field(
        True,
        description="Whether vasp.powerups.add_common_powerups adds a small gap "
        "multiply task for static and NSCF calculations",
    )
    VASP_ADD_MODIFY_INCAR: bool = Field(
        False,
        description="Whether vasp.powerups.add_common_powerups adds a modify incar "
        "task",
    )
    VASP_ADD_STABILITY_CHECK: bool = Field(
        False,
        description="Whether vasp.powerups.add_common_powerups adds a stability check "
        "task for structure optimization calculations",
    )
    VASP_ADD_WF_METADATA: bool = Field(
        False,
        description="Whether vasp.powerups.add_common_powerups adds structure metadata "
        "to a workflow",
    )
    VASP_HALF_KPOINTS_FIRST_RELAX: bool = Field(
        False,
        description="Whether to use only half the k-point density in the initial"
        "relaxation of a structure optimization for faster performance",
    )
    VASP_RELAX_MAX_FORCE: float = Field(
        0.25,
        description="Maximum force allowed on each atom for successful structure "
        "optimization",
    )
    VASP_VOLUME_CHANGE_WARNING_TOL: float = Field(
        0.2,
        description="Maximum volume change allowed in VASP relaxations before the "
        "calculation is tagged with a warning",
    )
    VASP_DEFUSE_UNSUCCESSFUL: Union[str, bool] = Field(
        "fizzle",
        description="Three-way toggle on what to do if the job looks OK but is actually"
        "unconverged (either electronic or ionic). "
        "True -> mark job as COMPLETED, but defuse children. "
        "False --> do nothing, continue with workflow as normal. "
        "'fizzle' --> throw an error (mark this job as FIZZLED)",
    )
    VASP_CUSTODIAN_MAX_ERRORS: int = Field(
        5, description="Maximum number of errors to correct before custodian gives up"
    )
    VASP_STORE_VOLUMETRIC_DATA: Optional[Tuple[str]] = Field(
        None, description="Store data from these files in database if present"
    )
    VASP_STORE_ADDITIONAL_JSON: bool = Field(
        False,
        description="Ingest any additional JSON data present into database when "
        "parsing VASP directories useful for storing duplicate of FW.json",
    )
    VASP_RUN_BADER: bool = Field(
        False,
        description="Whether to run the Bader program when parsing VASP calculations."
        "Requires the bader command to be on the path.",
    )

    class Config:
        """Pydantic config settings."""

        env_prefix = "atomate"

    @root_validator(pre=True)
    def load_default_settings(cls, values):
        """
        Load settings from file or environment variables.

        Loads settings from a root file if available and uses that as defaults in
        place of built in defaults.

        This allows setting of the config file path through environment variables.
        """
        from monty.serialization import loadfn

        config_file_path: str = values.get("CONFIG_FILE", DEFAULT_CONFIG_FILE_PATH)

        new_values = {}
        if Path(config_file_path).exists():
            new_values.update(loadfn(config_file_path))

        return new_values


settings = Settings()