# 同軸の段付き工具：指定直進 envelope の合成実験

細い先端が穴を通過できても，後ろの太い柄が障害物に当たる例を検出します．既存 `screen-tool` の円筒検査を，明示した2成分へ適用する実験です．製品CLIの追加機能ではありません．

## 計算する範囲

- 入力は mm・assembly 座標系の1個の有効な solid STEP と，共通 tip・unit axis・非負 travel，2成分それぞれの radius・length・backset です．backset は共通 tip から軸の後方へ測った距離です．
- 成分の初期区間は tip を基準に `[-backset-length, -backset]` です．軸方向に travel だけ進めると sweep 区間は `[-backset-length, travel-backset]` になります．各円筒は平らな端面を含みます．
- 成分の backset と半径は独立です．隙間，重複，省略された柄や治具を自動補完しません．実工具を完全に表現した保証はありません．
- 同じ入力 bytes から1個の private STEP snapshot を作り，両成分をその snapshot で検査します．元の live file が後から変更されない保証とは異なります．
- 初期と最終の相対 backset，および共通・成分の移動量を局所公差で照合します．大きい座標へ足し戻すだけの roundtrip では見えない丸め誤差も拒否します．既存円筒の端点・軸・体積・退化検査はそのまま使います．

工具の holder/shank を含む形状を省略した到達判定の限界は，[Nelaturi らの support accessibility 論文](https://arxiv.org/html/1904.12117v3)でも議論されています．この実験は，そのうち指定済みの軸方向直進に限った幾何検査です．論文の除去計画や工具接触モデルを実装したものではありません．

## 判定と限界

両成分が `model_clear` のときだけ，全体を `model_clear` とします．1成分に確かな `interference` があれば既知の障害として残し，他成分が `indeterminate` なら `coverage_complete=false` を併記します．接触，微小正体積，kernel 失敗などを clear にしません．`coverage_complete` は2成分の判定が決着した意味であり，実工具形状の網羅性や製造品質の保証ではありません．

全成分の判定と距離が有効な場合のみ，最小距離を集約します．接触などで判定が未確定なら集約距離は null です．成分 sweep 同士が重なる場合があるので，交差体積を単純合算しません．`union_intersection_volume_mm3` は常に null です．成分別体積は full report で確認できます．

数値 epsilon は kernel 判定の閾値です．印刷公差や必要な作業隙間ではありません．nominal CAD 形状以外の造形変形，支持材の造形不良，工具の曲げ，指や把持部，除去力，支持破壊，破損，実際の除去成功は未評価です．横移動，回転，経路探索も行いません．実物検証は未実施です．

障害物は入力者が定義します．支持材との意図した接触や除去対象を自動識別・除外しません．複数の独立 solid を受け付ける機能もありません．

## 固定した独立 oracle

20×20×1 mm の slab，z=0..1，中心の貫通穴半径2.5 mmを使います．共通の初期 tip は (0,0,-1)，軸は +Z です．先端は半径1.5・長さ2・backset0，柄は半径3・長さ4・backset2 mmです．

| travel (mm) | 先端 | 柄 | 全体 |
|---|---|---|---|
| 2.5 | 穴との隙間1 mm | slab手前に0.5 mm | model_clear |
| 3 | 穴との隙間1 mm | slab下面へ端面接触，体積0 | indeterminate |
| 4 | 穴との隙間1 mm | 穴の外側に環状干渉，体積2.75π mm³ | interference |

90°のY軸回転後に (11,-7,5) mm 平行移動した同じ3条件も検査します．期待値は STEP import や Boolean 結果から逆算せず，寸法と区間関係から事前に決めています．`preregistered.json` は実行時も測定前に書き出します．

## 再現

既存 geometry extra の CadQuery 2.7.0 と OCCT 7.8.1.1 を使用しました．実験用に別の依存関係を追加していません．公開 repo の root で実行します．出力先は新規 directory にしてください．

```sh
python3 experiments/mechanical-ci/stepped-tool/reproduce.py --output /tmp/stepped-tool-run
python3 -m unittest discover -s experiments/mechanical-ci/tests -p test_stepped_tool.py -v
python3 experiments/mechanical-ci/stepped-tool/review/verify.py experiments/mechanical-ci/stepped-tool/screen.py
python3 scripts/validate_repository.py --check-sensitive-patterns
```

任意の適合入力は `screen.py input.json --output new-report.json` で検査できます．既存入力・出力への上書きは拒否します．この実験の outcome による exit code gate は未実装であり，呼出し側は report の `outcome` と `coverage_complete` を読む必要があります．

`results/` に合成STEP・入力・full report・preregistered oracle・manifestを収録します．STEP exportの日時などにより再生成 bytes が変わる場合があります．再現の主要条件は，固定寸法・判定・成分別距離と体積の oracle 一致です．各実行の bytes はその実行の manifest で結び付けます．第三者 binary，製品CAD，写真は含めません．新しい license は選定していません．

`REVIEW_HISTORY.md` は初版から修正した境界と，初回の誤った test 期待値を記録します．

独立レビューの `review/verify.py` と `review/result.json` は，固定した screen の SHA に対して，37°回転・成分順序の入替6条件，巨大座標4条件，集約9条件を検査した記録です．screen を変更した場合はこの記録を新しい版の証拠として流用できません．
