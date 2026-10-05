# 支持材の指令Z面とCAD下面：名目距離の応答

固定した合成棚を PrusaSlicer 2.9.2 でスライスし，support contact distance の設定差が，指定した中央窓内の支持材吐出指令Zへどう反映されるか調べます．実物の air gap，接触，剥がしやすさ，除去力を測る実験ではありません．製品CLIへ新しい判定を追加していません．

## 結果

物体の設定層高は0.2 mm，CAD棚下面は機械座標Z=12 mm，固定XY窓は [85,84]..[95,96] mmです．同じSTL・姿勢・profileを使い，contact distance だけを変えました．

| 設定contact distance (mm) | 窓内の最高support指令Z (mm) | CAD下面12−support指令Z (mm) | 最初に観測したmodel plane |
|---|---|---|---|
| 0 | 12.0 | 0.0 | Z12.2，Solid infill，HEIGHT 0.2 |
| 0.1 | 11.7 | 0.3 | Z12.2，Bridge infill，HEIGHT 0.4 |
| 0.2 | 11.6 | 0.4 | Z12.2，Bridge infill，HEIGHT 0.4 |
| 0.3 | 11.5 | 0.5 | Z12.2，Bridge infill，HEIGHT 0.4 |

この固定profileと窓では，非ゼロの設定差0.1 mmがsupport指令面にも0.1 mmで残りました．`support_material_synchronize_layers=0` であり，物体の層高0.2 mmを，すべてのsupport Zにも適用できる量子化規則とは扱えません．別slicer・profile・形状への一般化や，実物寸法が0.1 mm精度で変わるという主張はしていません．設定0はflow roleとHEIGHTが変わる別の条件です．この表は印刷設定の推奨ではありません．

非ゼロ3条件の事前予測は，中央のthick bridgeが print Z12.2・height0.4という条件で，support指令面が `12.2−0.4−設定値` になるというものです．原本のrole・HEIGHT・解決済み設定で条件を確認し，結果が一致しました．設定値そのものが，この名目距離や実物の隙間と等しいわけではありません．

## 範囲と定義

`audit.py` は，明示した機械座標系の水平CAD面と閉XY矩形を受け取ります．正の移動吐出を持つ，平面内の `Support material` / `Support material interface` 中心線が矩形と交わる場合だけ選びます．線幅を加えて窓を広げず，両端が窓外でも横切る線分を選びます．既知の最高Zとsource行を保存し，coverageが完全な場合のみCAD面との差を返します．負の差もそのまま残します．支持材が観測されなければ距離は null です．

未知role・欠落したwidth/height・非平面吐出・静止吐出がある場合，既知の観測は残して最終距離を null にします．width/heightは中心線選択には数学的に不要ですが，既存の保守的なmetadata coverage方針を引き継いでいます．静止吐出は，位置が分かる場合もこの移動経路監査の対象外です．未対応の単位変更・座標offset・円弧などは入力エラーで拒否します．

補助のmodel plane観測は，明示したmodel roleに限ります．skirt・brim・wipe towerは含めません．coverageが不完全なときは，この既知subsetが実際の最初のmodel layerだとは主張しません．

G-codeとplane JSONはそれぞれ1回読み取った同じbyte bufferをhash化・解析します．元のlive pathがその後も不変であるという証明ではありません．また，既存parserの限定方言・浮動小数点演算に依存します．既知の極小E underflow制限を製品側で修正したものではありません．任意のG-code方言全体を検証したとは扱いません．

吐出指令ZやHEIGHTは，物理的なbead表面の測定値ではありません．特にbridge HEIGHTから物理下面を作り，supportとの接触やair gapを算出することはしません．造形不良，熱変形，材料異方性，支持材の付着，除去破損，保持力，実際の除去成功は未検証です．今回のprofileは公開済みの合成解析用profileであり，ユーザーの実機用profileではありません．

## 独立oracleと原本

- `oracles/preregistered-oracles.json` と7個の手書きG-codeは，実装前に固定した中心線・最高面・不完全coverageのoracleです．交差しない高い線分，端点接触，面より上のsupport，支持材なし等を含みます．
- `oracles/verify_implementation.py` は7fixturesと，整数orientation/矩形4辺交差による2,000線分の別方式oracleを検査します．監査本体はFractionによるslab clippingです．
- `oracles/slicer-study-plan.json` は新slice前の固定窓・面・設定・条件付き予測です．結果に合わせて窓や予測を動かしていません．
- `evidence.zip` は4条件のraw G-code，合成STL，profile，hash付き入力，full reports，provenance，manifestを含みます．絶対pathを含み得るlocal slicer logは除外しています．`summary.json` は同じarchive内のsummaryのbyte単位コピーです．
- 独立raw監査は別のDecimal modal parserと線分交差方式で，最高supportと最初のmodel planeのsource行集合，profile差，解決設定，manifestのhashを照合します．

## 再現

repo rootで実行します．通常のPython実行を使い，assertを無効化しないでください．reproducerは記録したDebian stable配布のPrusaSlicer 2.9.2+dfsg-1実行ファイルに固定しています．実行前にSHA256を照合し，異なるbinaryは実行しません．

Binary SHA256: `7beaf8cc8861dcb97803da73222bdee358992e02c13a8e2b6212ae4809c121d2`

```sh
python3 experiments/mechanical-ci/support-plane/reproduce.py --slicer /path/to/prusa-slicer --output /tmp/support-plane-new-run
python3 -m unittest discover -s experiments/mechanical-ci/tests -p test_support_plane.py -v
python3 experiments/mechanical-ci/support-plane/oracles/verify_implementation.py experiments/mechanical-ci/support-plane/audit.py
python3 experiments/mechanical-ci/support-plane/oracles/verify_raw_slices.py /tmp/support-plane-new-run
python3 scripts/validate_repository.py --check-sensitive-patterns
```

必要なruntime library検索pathは呼出し環境で与えます．再現scriptはソフトの導入やシステム設定変更を行いません．別OS/buildのbinaryはこの記録とは別の再現protocolが必要です．G-code生成時刻などによりhashが変わることがあるため，主要な再現条件は固定入力・解決設定・名目面・source行の独立照合です．各実行のhashはその実行内の原本を結び付けます．

## 一次資料

- [Prusa support material設定](https://help.prusa3d.com/article/support-material_1698)：top contactとbridge flow，設定0の異なる用途
- [PrusaSlicer 2.9.2 SupportMaterial.cpp](https://github.com/prusa3d/PrusaSlicer/blob/version_2.9.2/src/libslic3r/Support/SupportMaterial.cpp#L1383)：通常のcontact planeとthick bridgeのcontact planeを分ける実装
- [PrusaSlicer 2.9.2 GCode.cpp](https://github.com/prusa3d/PrusaSlicer/blob/version_2.9.2/src/libslic3r/GCode.cpp#L2563)：layerのprint Zとz_offsetの出力関係
- [PrusaSlicer 2.9.2 Flow.hpp](https://github.com/prusa3d/PrusaSlicer/blob/version_2.9.2/src/libslic3r/Flow.hpp)：bridge flowと通常の押出断面の区別

原本は今回の合成実験用です．製品CAD，写真，第三者binaryは含めません．新しいlicenseは選定していません．
