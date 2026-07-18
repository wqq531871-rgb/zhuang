本目录是 packing-system 的运行时数据区，不要提交到 GitHub。

结构：
  data/     Excel 测试集、UI 复制的 ui_inputs
  input/    接口拉取的原始 JSON（raw 等）
  output/   装箱结果 JSON / Excel 汇总
  runtime/  看板日志、exports、临时 YAML

对应代码仓库：同级文件夹 packing-system
可用环境变量 PACKING_WORKSPACE 指向本目录（或其它路径）。
