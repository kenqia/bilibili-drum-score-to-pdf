# #59 最终集成证据

软件冻结提交 `c78bf48236a5127405ca36ed51e80755d246c4dd`，审阅提交 `d86ff9185a9622d1980934c8cc263670674c240e`，二者文件树相同。

root 完整回归命令如下，87项通过、34.875秒、无跳过。

```sh
uv run --isolated --with-requirements skills/bilibili-drum-score-to-pdf/scripts/requirements.txt --with mido==1.3.3 python -m unittest discover -s tests -v
```

`formal-entry-replay.json` 记录已验收四条 PDF 路线的正式 CLI 恢复与导出，保存的 output、PDF hash 和审阅状态不变；三个 MIDI 记录恢复相同。不计为新视觉判断。`ci-summary.json` 是独立合成矢量双跑与四类拒绝检查，只验证确定性软件。`standards-review.md` 和 `spec-review.md` 为两轴独立审阅，修复后无剩余发现。

完整日志保存在 `/home/kenqia/issue54-recovery-evidence/`。当前支持近似可播放 MIDI，未进行音源渲染或听感验收，原可靠音乐准确性门槛未通过。
