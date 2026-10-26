from scripts.run_benchmarks import run_benchmarks


async def test_measured_benchmark_cohorts(tmp_path):
    result, path = await run_benchmarks(cases_per_cohort=1, work_dir=tmp_path)
    assert result["cases_per_runner"] == 5
    assert result["total_executions"] == 10
    assert [(row["saga"], row["naive"]) for row in result["metrics"]] == [
        (0, 1),
        (1, 0),
        (0, 1),
        (1, 0),
        (0, 1),
    ]
    assert (path / "case_evidence.json").exists()
