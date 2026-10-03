# Finite escape search with independent STEP replay

原点に接続した有限6自由度mesh探索と，選択経路の独立BRep再生を分けた研究prototypeです．合成の開箱では脱出候補，閉箱では探索予算内の未発見を返します．実製品のCADやprivate inputは不要です．

## 再実行

Python 3.12で確認しました．新しい仮想環境を推奨します．依存をvendoringしません．

```sh
python3 -m venv /tmp/escape-venv
/tmp/escape-venv/bin/python -m pip install -r experiments/mechanical-ci/escape-search/requirements.txt
/tmp/escape-venv/bin/python experiments/mechanical-ci/escape-search/build_fixtures.py /tmp/escape-fixtures
/tmp/escape-venv/bin/python experiments/mechanical-ci/escape-search/experiment.py \
  --fixed /tmp/escape-fixtures/open.step --moving /tmp/escape-fixtures/moving.step \
  --seed 17 --proposals 500 --output /tmp/escape-open.json
/tmp/escape-venv/bin/python experiments/mechanical-ci/escape-search/experiment.py \
  --fixed /tmp/escape-fixtures/closed.step --moving /tmp/escape-fixtures/moving.step \
  --seed 17 --proposals 500 --output /tmp/escape-closed.json
/tmp/escape-venv/bin/python -m unittest discover -s experiments/mechanical-ci/escape-search/tests -v
```

生成先directoryと結果fileは新規pathにしてください．既存pathへの上書きは拒否します．exit 0は実験完走を表し，保持の合格ではありません．JSONの`result`を読んでください．

## 方法と実測

- fixture generatorとcheckerを別processにし，checkerは凍結STEPを読込．再生時もSTEPを再読込
- 単位mm/degree．姿勢は並進XYZとroll/pitch/yaw，初期moving bounding box中心のまわりにRz·Ry·Rx回転
- seeded treeの受理nodeに親を保存．各edgeの中間点をFCLの表面meshで検査し，終点のみの判定を避ける
- サンプル間の点移動上限は並進norm＋半径上限×Euler角差の絶対値和．探索0.2 mm，再生0.1 mm
- goalはmoving bounding box全体がfixed bounding boxより0.01 mm上．上方だけが対象で，側方脱出は対象外
- 原点のBRep正体積干渉とmesh接触を拒否．選択経路では正体積干渉threshold 1e-7 mm³を使用
- 結果に入力hash，依存版，提案予算，受理node数，選択経路，独立再生数を記録

`results/`は公開toyの実測JSONです．同じseedでも依存版やkernel/platform差で探索順や境界判定が変わり得ます．生成STEPの日時だけを固定しています．数値を実製品へ転用できません．

## 限界

探索は完全でも連続でもありません．meshは接触滑りや完全包含を正しく扱えない場合があり，離散edgeはサンプル間の干渉を見落とせます．独立BRep再生も離散です．閉箱については選択した遊び経路だけを再生し，探索graph全体をBRep確認していません．

上方goalが単純な並進でもdomain外になる入力は拒否します．このsanity checkは任意geometryに対する可到達性解析ではありません．private inputへ応用する場合はgoal，bounds，pivot，tessellation，刻み，接触の扱いを検討し直す必要があります．

弾性変形，支持材除去，積層，材料，接触力，摩擦，公差，破壊，実測，保持力は対象外です．`sampled_escape_candidate`も連続・実物の脱出証明ではありません．

## 依存条件

- CadQuery 2.7.0: Apache-2.0，内部kernelと推移依存の条件は別途確認
- python-fcl 0.7.0.11: BSD-3-Clause，FCL: BSD-3-Clause
- NumPy / SciPy: BSD-3-Clause

[CadQuery license](https://github.com/CadQuery/cadquery/blob/master/LICENSE)，[python-fcl license](https://github.com/BerkeleyAutomation/python-fcl/blob/master/LICENSE)，[FCL license](https://github.com/flexible-collision-library/fcl/blob/master/LICENSE)．自作コードへのlicense付与は行っていません．
