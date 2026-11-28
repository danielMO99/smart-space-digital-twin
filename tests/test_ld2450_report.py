"""Contract examples and actual C++ policy; no broker or hardware."""
import json
import os
from pathlib import Path
import subprocess
from typing import Literal
from uuid import UUID
import pytest
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]
class Slot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slot: StrictInt = Field(ge=1, le=3)
    x_mm: StrictInt | None = Field(ge=-32767, le=32767)
    y_mm: StrictInt | None = Field(ge=-32767, le=32767)
    speed_mm_s: StrictInt | None = Field(ge=-32768, le=32767)
    resolution_mm: StrictInt | None = Field(ge=0, le=32767)
    @model_validator(mode="after")
    def complete(self):
        values = [self.x_mm,self.y_mm,self.speed_mm_s,self.resolution_mm]
        if any(v is None for v in values) and not all(v is None for v in values):
            raise ValueError("Partial slot")
        if self.x_mm == self.y_mm == 0:
            raise ValueError("Origin is not a decoded present slot")
        return self
class Diagnostics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invalid_reports: StrictInt = Field(ge=0)
    offline_reports: StrictInt = Field(ge=0)
    decimated_reports: StrictInt = Field(ge=0)
    enqueue_failures: StrictInt = Field(ge=0)
    previous_callback_max_us: StrictInt = Field(ge=0)
class Report(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_name: Literal["smartspace.ld2450.frame"] = Field(alias="schema")
    version: Literal[1]
    device: Literal["smartspace-esp32"]
    boot_id: UUID
    seq: StrictInt = Field(ge=1, le=2**64-1)
    rx_us: StrictInt = Field(ge=0, le=2**63-1)
    time_reference: Literal["esp_processing_monotonic"]
    selected_seq: StrictInt = Field(ge=1, le=2**64-1)
    min_interval_us: StrictInt = Field(ge=0, le=2**64-1)
    targets: list[StrictInt] = Field(max_length=3)
    slots: list[Slot] = Field(min_length=3,max_length=3)
    diagnostics: Diagnostics
    @model_validator(mode="after")
    def coherent(self):
        if [s.slot for s in self.slots] != [1,2,3]: raise ValueError("Slot order")
        if self.targets != [s.slot for s in self.slots if s.x_mm is not None]: raise ValueError("Target references")
        if self.selected_seq > self.seq: raise ValueError("Selection sequence")
        return self

EXAMPLES = json.loads((ROOT/'docs/contracts/ld2450-frame-v1.examples.json').read_text())
@pytest.mark.parametrize('example',EXAMPLES)
def test_contract_examples(example):
    report = Report.model_validate(example['payload'])
    assert json.loads(report.model_dump_json(by_alias=True)) == example['payload']
@pytest.mark.parametrize('value',[float('nan'),float('inf'),'',True,1.25])
def test_contract_rejects_invalid_numbers(value):
    payload = json.loads(json.dumps(EXAMPLES[1]['payload']))
    payload['slots'][0]['x_mm'] = value
    with pytest.raises(ValueError): Report.model_validate(payload)
def test_contract_rejects_partial_and_false_empty():
    payload = json.loads(json.dumps(EXAMPLES[1]['payload']))
    payload['slots'][0]['speed_mm_s'] = None
    with pytest.raises(ValueError): Report.model_validate(payload)
    payload = json.loads(json.dumps(EXAMPLES[1]['payload']))
    payload['targets'] = []
    with pytest.raises(ValueError): Report.model_validate(payload)
def test_actual_cpp_policy(tmp_path):
    compiler = os.environ.get('SMARTSPACE_XTENSA_CXX')
    if not compiler: pytest.skip('Set SMARTSPACE_XTENSA_CXX for compile-time firmware tests')
    subprocess.run([compiler,'-std=gnu++20','-c',str(ROOT/'tests/test_ld2450_report_core.cpp'),
                    '-o',str(tmp_path/'report-tests.o')],check=True,capture_output=True,text=True)
