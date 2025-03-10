"""Define common EOS flow agnostic to electronic-structure code."""

from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np
from jobflow import Flow, Maker

from atomate2.common.jobs.eos import PostProcessEosEnergy, apply_strain_to_structure

if TYPE_CHECKING:
    from pathlib import Path

    from jobflow import Job
    from pymatgen.core import Structure

    from atomate2.common.jobs.eos import EOSPostProcessor


@dataclass
class CommonEosMaker(Maker):
    """
    Generate equation of state data.

    First relax a structure using relax_maker.
    Then perform a series of deformations on the relaxed structure, and
    evaluate single-point energies with static_maker.

    Parameters
    ----------
    name : str
        Name of the flows produced by this maker.
    initial_relax_maker : .Maker | None
        Maker to relax the input structure, defaults to None (no initial relaxation).
    eos_relax_maker : .Maker
        Maker to relax deformed structures for the EOS fit.
    static_maker : .Maker | None
        Maker to generate statics after each relaxation, defaults to None.
    strain : tuple[float]
        Percentage linear strain to apply as a deformation, default = -5% to 5%.
    number_of_frames : int
        Number of strain calculations to do for EOS fit, default = 6.
    postprocessor : .atomate2.common.jobs.EOSPostProcessor
        Optional postprocessing step, defaults to
        `atomate2.common.jobs.PostProcessEosEnergy`.
    _store_transformation_information : .bool = False
        Whether to store the information about transformations. Unfortunately
        needed at present to handle issues with emmet and pydantic validation
        TODO: remove this when clash is fixed
    """

    name: str = "EOS Maker"
    initial_relax_maker: Maker = None
    eos_relax_maker: Maker = None
    static_maker: Maker = None
    linear_strain: tuple[float, float] = (-0.05, 0.05)
    number_of_frames: int = 6
    postprocessor: EOSPostProcessor = field(default_factory=PostProcessEosEnergy)
    _store_transformation_information: bool = False

    def make(self, structure: Structure, prev_dir: str | Path = None) -> Flow:
        """Run an EOS flow.

        Parameters
        ----------
        structure : Structure
            A pymatgen structure object.
        prev_dir : str or Path or None
            A previous calculation directory to copy output files from.

        Returns
        -------
        .Flow, an EOS flow
        """
        jobs: dict[str, list[Job]] = {key: [] for key in ("relax", "static", "utility")}

        job_types: tuple[str, ...] = (
            ("relax", "static") if self.static_maker else ("relax",)
        )
        flow_output: dict[str, dict] = {
            key: {
                quantity: []
                for quantity in ("energy", "volume", "stress", "structure", "dir_name")
            }
            for key in job_types
        }

        # First step: optional relaxation of structure
        if self.initial_relax_maker:
            relax_flow = self.initial_relax_maker.make(
                structure=structure, prev_dir=prev_dir
            )
            relax_flow.name = "EOS equilibrium relaxation"

            try:
                if len(relax_flow.jobs) > 1:
                    for job in relax_flow.jobs:
                        job.append_name(" EOS equilibrium relaxation")
            except AttributeError:
                pass
            flow_output["initial_relax"] = {
                "E0": relax_flow.output.output.energy,
                "V0": relax_flow.output.structure.volume,
            }
            structure = relax_flow.output.structure
            prev_dir = relax_flow.output.dir_name
            jobs["relax"].append(relax_flow)

            if self.static_maker:
                equil_static = self.static_maker.make(
                    structure=structure, prev_dir=prev_dir
                )
                equil_static.name = "EOS equilibrium static"
                flow_output["initial_static"] = {
                    "E0": equil_static.output.output.energy,
                    "V0": equil_static.output.structure.volume,
                }
                jobs["static"].append(equil_static)

        strain_l, strain_delta = np.linspace(
            self.linear_strain[0],
            self.linear_strain[1],
            self.number_of_frames,
            retstep=True,
        )

        if self.initial_relax_maker:
            # Cell without applied strain already included from relax/equilibrium steps.
            # Perturb this point (or these points) if included
            zero_strain_mask = np.abs(strain_l) < 1e-15
            if np.any(zero_strain_mask):
                nzs = len(strain_l[zero_strain_mask])
                shift = strain_delta / (nzs + 1.0) * np.linspace(-1.0, 1.0, nzs)
                strain_l[np.abs(strain_l) < 1e-15] += shift

        deformation_l = [(np.identity(3) * (1.0 + eps)).tolist() for eps in strain_l]

        # apply strain to structures, return list of transformations
        transformations = apply_strain_to_structure(structure, deformation_l)
        jobs["utility"] += [transformations]

        for frame_idx in range(self.number_of_frames):
            if self._store_transformation_information:
                with contextlib.suppress(Exception):
                    # write details of the transformation to the
                    # transformations.json file. This file will automatically get
                    # added to the task document and allow the elastic builder
                    # to reconstruct the elastic document. Note the ":"
                    # is automatically converted to a "." in the filename.
                    self.eos_relax_maker.write_additional_data[
                        "transformations:json"
                    ] = transformations.output[frame_idx]

            relax_job = self.eos_relax_maker.make(
                structure=transformations.output[frame_idx].final_structure,
                prev_dir=prev_dir,
            )
            relax_job.name += f" deformation {frame_idx}"
            try:
                if len(relax_job.jobs) > 1:
                    for job in relax_job.jobs:
                        job.append_name(f" deformation {frame_idx}")
            except AttributeError:
                pass
            jobs["relax"].append(relax_job)

            if self.static_maker:
                static_job = self.static_maker.make(
                    structure=relax_job.output.structure,
                    prev_dir=relax_job.output.dir_name,
                )
                static_job.name += f" {frame_idx}"
                jobs["static"].append(static_job)

        for key in job_types:
            for idx in range(len(jobs[key])):
                output = jobs[key][idx].output.output
                dir_name = jobs[key][idx].output.dir_name
                flow_output[key]["energy"] += [output.energy]
                flow_output[key]["volume"] += [output.structure.volume]
                flow_output[key]["stress"] += [output.stress]
                flow_output[key]["structure"] += [output.structure]
                flow_output[key]["dir_name"] += [dir_name]

        if self.postprocessor is not None:
            min_points = self.postprocessor.min_data_points
            if len(jobs["relax"]) < min_points:
                raise ValueError(
                    "To perform least squares EOS fit with "
                    f"{type(self.postprocessor).__name__}, you must specify "
                    f"self.number_of_frames >= {min_points}."
                )

            post_process = self.postprocessor.make(flow_output)
            post_process.name = self.name + " postprocessing"
            flow_output = post_process.output
            jobs["utility"] += [post_process]

        job_list = []
        for val in jobs.values():
            job_list += val

        return Flow(jobs=job_list, output=flow_output, name=self.name)
