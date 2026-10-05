# 検証履歴

- 初版の6条件は，tip clear・柄の clear/contact/interference と剛体変換後の解析 oracle に一致しました．
- 独立レビューで，backset の単なる roundtrip では巨大座標の丸めを見逃す例が見つかりました．tip=1e16，backset=3 が実際の差4へ丸められても，足し戻すと元 tip に一致します．初期・最終の相対 backset と移動量を直接比較する検査を追加し，正負の巨大座標と終端で消える backset を回帰テストにしました．
- 独立レビューにより，実験CLIでも既存出力拒否と exclusive creation を追加しました．入力 alias と別 writer の先行作成もテストします．
- zero-travel の追加テストで，距離1 mmという期待値が失敗しました．先端は slab より下へ1 mm，穴の縁より内側へ1 mmあり，最近距離は斜めの sqrt(2) mmです．oracle を幾何関係に基づいて訂正しました．kernel の返値を単に許容する変更ではありません．主要6条件の oracle は変更していません．
- source STEP を1成分目の後に変更する fault injection で，2成分目も同じ snapshot bytes を使うことを確認します．snapshot 自体の破損は report を返さず拒否します．live source の不変性を証明したとは扱いません．
