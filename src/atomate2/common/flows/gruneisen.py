"""Flows for calculating Grueneisen-Parameters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from jobflow import Flow, Maker

from atomate2.common.jobs.gruneisen import (
    compute_gruneisen_param,
    shrink_expand_structure,
)

if TYPE_CHECKING:
    from pymatgen.core.structure import Structure

    from atomate2.aims.jobs.base import BaseAimsMaker
    from atomate2.common.flows.phonons import BasePhononMaker
    from atomate2.forcefields.jobs import ForceFieldRelaxMaker
    from atomate2.vasp.jobs.base import BaseVaspMaker


@dataclass
class BaseGruneisenMaker(Maker, ABC):
    """
    Maker to calculate Grueneisen parameters with DFT/force field code and Phonopy.

    Calculate the harmonic phonons of a material for and compute Grueneisen parameters.
    Initially, a tight structural relaxation is performed to obtain a structure without
    forces on the atoms. The optimized structure (ground state) is further expanded and
    shrunk by 1 % of its volume. Subsequently, supercells with one displaced atom are
    generated for all the three structures (ground state, expanded and shrunk volume)
    and accurate forces are computed for these structures. With the help of phonopy,
    these forces are then converted into a dynamical matrix. This dynamical matrix of
    three structures is then used as input phonopy Grueneisen api to compute Grueneisen
    parameters are computed.


    Parameters
    ----------
    name : str
        Name of the flows produced by this maker.
    bulk_relax_maker: .ForceFieldRelaxMaker, .BaseAimsMaker, .BaseVaspMaker, or None
        A maker to perform an initial tight relaxation on the bulk.
    code: str
        determines the dft or force field code.
    const_vol_relax_maker: .ForceFieldRelaxMaker, .BaseAimsMaker,
        .BaseVaspMaker, or None. A maker to perform a tight relaxation
        on the expanded and shrunk structures at constant volume.
    kpath_scheme: str
        scheme to generate kpoints. Please be aware that
        you can only use seekpath with any kind of cell
        Otherwise, please use the standard primitive structure
        Available schemes are:
        "seekpath", "hinuma", "setyawan_curtarolo", "latimer_munro".
        "seekpath" and "hinuma" are the same definition but
        seekpath can be used with any kind of unit cell as
        it relies on phonopy to handle the relationship
        to the primitive cell and not pymatgen
    mesh: tuple
        Mesh numbers along a, b, c axes used for Grueneisen parameter computation.
    phonon_maker: .PhononMaker
        Maker used to perform phonon computations
    perc_vol: float
        Percent volume to shrink and expand ground state structure
    compute_gruneisen_param_kwargs: dict
        Keyword arguments passed to :obj:`compute_gruneisen_param`.
    """

    name: str = "Gruneisen"
    bulk_relax_maker: ForceFieldRelaxMaker | BaseVaspMaker | BaseAimsMaker | None = None
    code: str = None
    const_vol_relax_maker: ForceFieldRelaxMaker | BaseVaspMaker | BaseAimsMaker = None
    kpath_scheme: str = "seekpath"
    phonon_maker: BasePhononMaker = None
    perc_vol: float = 0.01
    mesh: tuple = field(default_factory=lambda: (20, 20, 20))
    compute_gruneisen_param_kwargs: dict = field(default_factory=dict)
    symprec: float = 1e-4

    def make(self, structure: Structure) -> Flow:
        """
        Optimizes structure and runs phonon computations.

        Phonon computations are run for ground state, expanded and shrunk
        volume structures. Then, Grueneisen parameters are computed from
        this three phonon runs.

        Parameters
        ----------
        structure: Structure

        """
        jobs = []  # initialize an empty list for jobs to be run

        # initialize an dict to store optimized structures
        opt_struct = dict.fromkeys(("ground", "plus", "minus"), None)

        if (
            self.bulk_relax_maker is not None
        ):  # Optional job to relax the initial structure
            bulk = self.bulk_relax_maker.make(structure)
            jobs.append(bulk)
            opt_struct["ground"] = bulk.output.structure
        else:
            opt_struct["ground"] = structure

        # Add job to get expanded and shrunk volume structures
        struct_dict = shrink_expand_structure(
            structure=bulk.output.structure, perc_vol=self.perc_vol
        )
        jobs.append(struct_dict)

        # get expanded structure
        const_vol_struct_plus = self.const_vol_relax_maker.make(
            structure=struct_dict.output["plus"]
        )
        # add relax job at constant volume for expanded structure
        jobs.append(const_vol_struct_plus)

        opt_struct["plus"] = (
            const_vol_struct_plus.output.structure
        )  # store opt struct of expanded volume

        # get shrunk structure
        const_vol_struct_minus = self.const_vol_relax_maker.make(
            structure=struct_dict.output["minus"]
        )
        # add relax job at constant volume for shrunk structure
        jobs.append(const_vol_struct_minus)

        opt_struct["minus"] = (
            const_vol_struct_minus.output.structure
        )  # store opt struct of expanded volume

        phonon_yaml_dirs = dict.fromkeys(("ground", "plus", "minus"), None)
        phonon_imaginary_modes = dict.fromkeys(("ground", "plus", "minus"), None)
        for st in opt_struct:
            # phonon run for all 3 optimized structures (ground state, expanded, shrunk)
            phonon_job = self.phonon_maker.make(structure=opt_struct[st])

            # change default phonopy.yaml file name to ensure workflow can be
            # run without having to create folders, thus
            # prevent overwriting and easier to identify yaml file belong
            # to corresponding phonon run
            phonon_job.jobs[-1].function_kwargs.update(
                filename_phonopy_yaml=f"{st}_phonopy.yaml",
                filename_band_yaml=f"{st}_phonon_band_structure.yaml",
                filename_dos_yaml=f"{st}_phonon_dos.yaml",
                filename_bs=f"{st}_phonon_band_structure.pdf",
                filename_dos=f"{st}_phonon_dos.pdf",
            )
            jobs.append(phonon_job)
            # store each phonon run task doc
            phonon_yaml_dirs[st] = phonon_job.output.jobdirs.taskdoc_run_job_dir
            phonon_imaginary_modes[st] = phonon_job.output.has_imaginary_modes

        # get Gruneisen parameter from phonon runs yaml with phonopy api
        get_gru = compute_gruneisen_param(
            code=self.code,
            kpath_scheme=self.kpath_scheme,
            mesh=self.mesh,
            phonopy_yaml_paths_dict=phonon_yaml_dirs,
            structure=opt_struct["ground"],
            symprec=self.symprec,
            phonon_imaginary_modes_info=phonon_imaginary_modes,
            **self.compute_gruneisen_param_kwargs,
        )

        jobs.append(get_gru)

        return Flow(jobs, output=get_gru.output)

    @property
    @abstractmethod
    def prev_calc_dir_argname(self) -> str | None:
        """Name of argument informing static maker of previous calculation directory.

        As this differs between different DFT codes (e.g., VASP, CP2K), it
        has been left as a property to be implemented by the inheriting class.

        Note: this is only applicable if a relax_maker is specified; i.e., two
        calculations are performed for each ordering (relax -> static)
        """