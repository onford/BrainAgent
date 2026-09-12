"""Join verified profile evidence, regression reports and actual browser receipts."""
from pathlib import Path
import argparse,json,xml.etree.ElementTree as ET
from app.preprocessing.storage import write_json,file_hash
from app.preprocessing.units import engine_hash


def read(path):return json.loads(path.read_text(encoding='utf-8'))
def link(path,label):return f'[{label}]({path.resolve().as_posix()})'


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--browser',type=Path,required=True);p.add_argument('--audit-root',type=Path,required=True);a=p.parse_args()
    matrix=read(a.output/'matrix.json');assert matrix['engine_sha256']==engine_hash(),'stale matrix'
    suites=list(ET.parse(a.output/'backend-tests-final.xml').getroot().iter('testsuite'))
    tests={k:sum(int(s.attrib.get(k,0)) for s in suites) for k in ('tests','failures','errors','skipped')}
    assert not tests['failures'] and not tests['errors']
    front=read(a.output/'frontend-tests-final.json');assert front['success']
    browser=read(a.browser/'browser-receipt.json');assert browser['passed'] and browser['catalogue_rows']==matrix['counts']['profiles']
    assert browser['numerically_verified_rows']==matrix['counts']['numerical_passed']
    for name,sha in browser['screenshots'].items():assert file_hash(a.browser/name)==sha
    assert file_hash(a.browser/'capabilities.json')==browser['capabilities_sha256']
    for item in browser['downloaded']:assert file_hash(a.browser/('downloaded-'+item['name']))==item['sha256']
    supplements=matrix['supplemental_cases']
    counts={**matrix['counts'],'supplemental_cases':len(supplements),'supplemental_passed':sum(s['status']=='passed' for s in supplements),'supplemental_numerical':sum(s.get('numerical_verified',False) for s in supplements),'supplemental_expected_rejections':sum(s.get('applicability_rejection_verified',False) for s in supplements),'backend':tests,'frontend_tests':front['numTotalTests'],'frontend_passed':front['numPassedTests'],'browser_completed_records':browser['completed_records']}
    files=[a.output/'matrix.json',a.output/'final-receipt-index.json',a.output/'backend-tests-final.xml',a.output/'frontend-tests-final.json',a.browser/'browser-receipt.json',a.output/'reproduced-environment.json',a.output/'native-assets.json',a.output/'source-dispatch-audit.json']
    files += [a.audit_root/name for name in ('frontend-build-final.log','frontend-typecheck-final.log','backend-tests-final.log','frontend-tests-final.log')]
    limitations=[
        '真实 EEG 只运行两个记录、两套配方；其余 profile 不标记真实数据验证通过。',
        '数值验证检验冻结来源函数与图适配器一致性，另有状态/泄漏/绑定/边界测试；未独立复现所有作者论文实验。',
        '来源批处理拟合器拒绝 subject_unlabeled/online，不静默转成 record_unlabeled。',
        'train/calibration 分区重放支持确定性前处理，尚不支持依赖上游模型、人工决定或外部参数端口的状态化重放。',
        'v2 有界图搜索可发现、选择、编译和执行候选；未接入旧 EEGNet 固定面板的评分、Trial 对齐与统一排名。',
        '取消在步骤边界生效，原生算法调用尚无逐调用即时取消；实际作者运行时仍受其 timeout 控制。',
        '方法提取已接入全量合同并通过入口测试；没有进行已配置外部语言模型的全量文献提取验收。',
    ]
    receipt=dict(schema_version='2',engine_sha256=matrix['engine_sha256'],counts=counts,files=[dict(path=str(f.resolve()),sha256=file_hash(f)) for f in files],browser_url=browser['url'],limitations=limitations)
    write_json(a.output/'acceptance.json',receipt)
    rows=[('当前源码单元 / op / profile',f"{counts['units']} / {counts['operations']} / {counts['profiles']}"),('逐 profile 编译 / 运行 / 数值 / 边界',f"{counts['compiled_passed']} / {counts['execution_passed']} / {counts['numerical_passed']} / {counts['boundary_passed']}"),('真实 EEG 覆盖的 profile',str(counts['real_data_passed'])),('补充组合与输入边界',f"{counts['supplemental_passed']} / {counts['supplemental_cases']}，其中数值运行 {counts['supplemental_numerical']}、预期拒绝 {counts['supplemental_expected_rejections']}"),('后端回归',f"{tests['tests']} 通过，失败 {tests['failures']}、错误 {tests['errors']}、跳过 {tests['skipped']}"),('前端测试',f"{counts['frontend_passed']} / {counts['frontend_tests']}；vue-tsc 与 Vite 构建通过"),('实际浏览器',f"{browser['catalogue_rows']} 条能力显示；编译并执行 {browser['completed_records']} 条记录；下载 axes/provenance 并保存哈希")]
    lines=['# 预处理全量接入验收结果','',f"当前执行器 SHA-256：`{matrix['engine_sha256']}`。首次冻结清单的全部 130 个身份保留，新增条目和合同修正见 inventory-amendment-final.json。",'', '| 检查 | 实际结果 |','|---|---|',*[f'| {k} | {v} |' for k,v in rows],'', '## 全量交付','',
        '- '+link(a.output/'matrix.md','全部单元 × op × profile 矩阵和参数合同'),
        '- '+link(a.output/'matrix.json','机器可读完整矩阵、来源与输入输出'),
        '- '+link(a.output/'final-receipt-index.json','逐项运行收据及补充组合收据'),
        '- '+link(a.output/'representative-methods.json','真实运行的完整 MethodSpec'),
        '- '+link(a.output/'representative-execution-plan.json','逐记录参数已绑定的 ExecutionPlan'),
        '- '+link(a.output.parent.parent/'preprocessing-integration-v2.md','架构、使用、依赖及兼容说明'),
        '- '+link(a.output/'acceptance.json','本验收摘要及证据文件哈希'),
        '- '+link(a.browser/'browser-receipt.json','实际 Edge 操作、下载与截图收据'),
        '', '## 实际流程','',
        'EEGMMIDB S001R04/S001R08：平均参考 → 1–40 Hz IIR → PICARD 拟合分支 → muscle slope 诊断 → 明确接受候选 → ICA 应用 → Epoch → baseline。另一配方使用 nanmedian 参考估计/应用模型、8–30 Hz Butterworth 和 window MAD 诊断分支。共 4 个结果，各 15 × 64 × 321，保存、回读、事件/Trial 映射及原始文件哈希检查通过。',
        '', '另有 ICLabel → 眼动掩码 → eye weights → targeted WICA，以及 ADJUST/FASTER → SASICA → 待决定/确认 → ICA apply 的完整合成数据分支收据。回归基线的零、一、二因素输入、训练边界及两种数据表示分别验证；连续参数不按无穷笛卡尔积声称覆盖。',
        '', '## 限制与未解决项','',*['- '+s for s in limitations],
        '', '本机所需原生运行时、作者代码及模型资产已实际安装和验证，没有以缺资产条目冒充运行通过。后续机器必须按锁文件及固定来源部署；前端会根据当前环境显示依赖缺失。前期失败与被后续实现取代的运行目录均保留，最终成功率只使用当前执行器哈希的证据。',
        '', '## 界面实测截图','',f"![全量能力与参数编排]({(a.browser/'catalogue.png').resolve().as_posix()})",'',f"![编译、执行和结果]({(a.browser/'execution.png').resolve().as_posix()})",'']
    (a.output/'acceptance.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(counts,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
