import os
import subprocess
import sys
from pathlib import Path

from shipment_review.cli import main, run

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_module_invocation_prints_utf8_verdict_over_pipe(tmp_path):
    # Runs `python -m shipment_review.cli <dir>` with stdout captured through a
    # pipe — the same path that crashes on a legacy-code-page Windows console.
    # Proves the __main__ guard works and output decodes as UTF-8.
    env = dict(os.environ, PYTHONPATH="src")
    result = subprocess.run(
        [sys.executable, "-m", "shipment_review.cli", str(tmp_path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=REPO_ROOT,
        env=env,
    )
    assert result.returncode == 0
    assert "審核結果：不可出貨" in result.stdout


def test_main_reconfigures_stdout_to_utf8_and_prints_verdict(tmp_path, monkeypatch):
    # Simulate a Windows console whose stdout defaults to a legacy code page that
    # cannot encode the mixed Traditional/Simplified Chinese verdict.
    class FakeStdout:
        def __init__(self):
            self.encoding = "cp1252"
            self.reconfigured_to = None
            self.buffer = []

        def reconfigure(self, *, encoding=None, **_):
            self.encoding = encoding
            self.reconfigured_to = encoding

        def write(self, text):
            self.buffer.append(text)
            return len(text)

        def flush(self):
            pass

    fake = FakeStdout()
    monkeypatch.setattr(sys, "stdout", fake)

    rc = main([str(tmp_path)])

    assert rc == 0
    assert fake.reconfigured_to == "utf-8"  # main forced UTF-8 before printing
    assert "審核結果：不可出貨" in "".join(fake.buffer)


def test_run_reports_missing_required_files(tmp_path):
    output = run(tmp_path)

    assert "審核結果：不可出貨" in output
    assert "缺少出貨審批文件" in output
    assert "缺少模組金核算表" in output


def test_cli_json_flag_emits_parseable_verdict(tmp_path, capsys):
    import json
    from shipment_review.cli import main
    rc = main([str(tmp_path), "--json"])  # empty dir → 不可出貨 (缺出貨審批 violation)
    assert rc == 0
    captured = capsys.readouterr()
    j = json.loads(captured.out)
    assert "status" in j


def test_run_reads_simple_text_case(tmp_path):
    (tmp_path / "出货审批.txt").write_text(
        "出货审批\n审批编码 202606091044000425537\n合同编号 ZHDEMO-20251124-01\n"
        "出货金额（元） 2,500.00 (贰仟伍佰元整)\n"
        "出货公司名称 四川代理商甲信息技术有限公司\n实际出货为：\n"
        "T5-3，1套智核ZClass5专业版系统V5.0\n收货人： 王钞\n"
        "备注 1、学校全称：示范乙校\n"
        "【财务确认】 审批人甲 已同意\n【产品管理经理】 审批人乙 已同意\n【智核CEO】 审批人丙 已同意\n",
        encoding="utf-8",
    )
    (tmp_path / "ZHDEMO-20251124-01.txt").write_text(
        "购销合同\n订单号码 ZHDEMO-20251124-01\n单位名称 四川代理商甲信息技术有限公司\n"
        "学校完整名称 示范乙校\nT5-3 智核ZClass5专业版系统 V5.0 套 1 2500 2500\n",
        encoding="utf-8",
    )
    (tmp_path / "模組金核算表.txt").write_text(
        "合同单号 采购公司名称 产品名称 型号 单位 数量 单价 金额 权益金\n"
        "ZHDEMO-20251124-01 四川代理商甲信息技术有限公司 T5-3 智核ZClass5专业版系统 V5.0 套 1 2500 2500 750\n",
        encoding="utf-8",
    )

    output = run(tmp_path)

    # The price-book module-fee stub is gone, and the approval 出货金额 (2,500)
    # reconciles with the module table's 单价×数量 (2500×1), so neither a module-fee
    # nor an amount-mismatch issue is raised.
    assert "模組金額無法自動核算" not in output
    assert "出貨金額" not in output
