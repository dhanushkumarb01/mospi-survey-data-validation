import pandas as pd

from evaluation.inject import InjectionPlan, write_injected
from pipeline.tests.synthetic import write_delivery


def test_every_injected_change_is_labelled_and_households_travel_with_persons(tmp_path):
    prepared, _ = write_delivery(tmp_path / "source")
    out, labels = write_injected(prepared, tmp_path / "injected", "2024", InjectionPlan(per_type=5, fabricated_fsus=1, copied_households=1, paradata_fsus=1, seed=3), states=("07",))
    before = pd.read_parquet(prepared).set_index(["MoSPI_record_key", "Person_Serial_No"])
    after = pd.read_parquet(out).set_index(["MoSPI_record_key", "Person_Serial_No"])
    changed = (before != after.reindex(before.index)).any(axis=1)
    changed_ids = {f"{k}|person={s}" for k, s in changed[changed].index}
    labelled = set(labels.loc[labels.level.eq("record"), "source_observation_id"])
    group_households = set(labels.loc[labels.level.eq("household"), "source_observation_id"])
    fabricated = set(labels.loc[labels.error_type.eq("fsu_fabrication"), "source_observation_id"])
    unexplained = {i for i in changed_ids - labelled if i.split("|person=")[0] not in group_households
                   and not any(i.split("|")[4] == f.split("|")[2] for f in fabricated)}
    assert not unexplained
    assert {"scale_x12", "scale_x100", "casual_wage_x10", "copied_household"} <= set(labels.error_type)
    assert (tmp_path / "injected" / "prepared_households.parquet").is_file()
    assert {"fsu_short_interviews", "fsu_one_day"} & set(labels.error_type)
