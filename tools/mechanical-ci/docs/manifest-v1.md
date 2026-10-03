# Manifest v1

実例は`examples/synthetic/open.json`と`blocked.json`です．未知のfieldやversionを黙って解釈しません．

## 必須field

- `schema_version`: 整数`1`
- `name`: 非空の識別名
- `units`: `mm`のみ
- `assembly_to_print`: 4×4の剛体変換行列．column vectorへ左から乗じ，平行移動もmm．最下行は`[0,0,0,1]`．回転部分の直交性とdeterminant +1を検査
- `artifacts`: 入力の相対POSIX path，SHA256，frame

artifact pathはmanifestのdirectory内に限定します．絶対path，親directoryへの脱出，root外を指すsymlink，hash不一致を拒否します．実際の単位と座標を正しく宣言する責任は入力作成側にあります．CAD/STL間の変換一致を形状で検証する機能はまだありません．

## 経路検査

`path_check`がある場合，`fixed`と`moving`のSTEP artifactが必要です．両方とも`frame: assembly`で，初期組立座標に配置された有効な単一solidである必要があります．

- `kind`: `sampled_translation`
- `frame`: `assembly`
- `waypoints_mm`: 2〜100個の3要素配列．初期STEP座標からの平行移動量で，増分ではありません
- `max_step_mm`: 各直線区間のサンプル間隔の上限．正の有限値
- `volume_tolerance_mm3`: 干渉とみなす体積の閾値．非負の有限値
- `expected_outcome`: `sampled_clear`または`collision_found`．CIの曖昧な成功を避けるため必須

全体は最大10,000サンプルに限定します．経路途中の全サンプルを記録します．`first_collision`より後ろの姿勢は，衝突を通過できるという意味ではありません．

体積による検査なので，接触面/線だけの接触や閾値以下の干渉はclear扱いになり得ます．すきま保証，公差解析，連続collision判定とは別です．

## スライス

`slicing`がある場合，`print_mesh`は印刷姿勢のSTLで`frame: print`，`profile`はflat INIで`frame: configuration`にします．

- `engine`: `PrusaSlicer`
- `expected_version`: 実行対象のversion，例`2.9.2`
- `center_mm`: slicerへ渡すXY中心
- `support_mode`: `none`または`auto`

`assembly_to_print`は既に書き出されたSTLの姿勢を説明するmetadataです．adapterがSTEPやSTLへその行列を再適用することはありません．slicerは`center_mm`への配置やbedへの移動を行うため，G-codeのmachine座標とassembly座標は同一ではありません．完全な逆写像は未実装で，結果の`assembly_to_print_geometry_verified`は常に`false`です．

INIは`gcode_comments=1`と`binary_gcode=0`が必須です．実行scriptを含む`post_process`，network/credential設定，重複keyは拒否します．supportは自動生成までで，局所enforcer/blockerの生成は未実装です．

## 結果の扱い

manifest/input/G-code/binaryのhash，backend version，検査結果をJSONに保存します．timestampや絶対machine pathをsummaryの識別情報には使いません．ただしslicerのlocal logにはpathが含まれることがあるため，公開しないでください．

`regression_passed`は指定した経路の期待結果との一致です．`unimplemented_gates`は実装上の事実であり，manifestから成功に上書きできません．FEMや実測校正を追加する際は，それぞれ固有の入力・判定基準・不確かさ・失敗状態を持つ新しいstageとして設計します．
