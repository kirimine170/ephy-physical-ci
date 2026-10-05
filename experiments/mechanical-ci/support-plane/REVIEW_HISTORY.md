# 検証履歴

- 実装前に，固定XY窓とCAD下面，7手書きG-code oracle，4条件のslice計画を独立に固定しました．
- 初版の補助model-plane集約では，既存non-support roleのallowlistを使っていました．独立reviewにより，skirt・brim・wipe towerをmodelと呼ばないよう，model roleの明示subsetへ絞りました．support最高面の主計算は変更していません．
- run-001で4条件すべてのpose gate・raw source行・名目面が一致しました．run-002ではprofile差がcontact設定だけであること，非ゼロ予測のbridge条件が成立していることを明示的に検証・記録しました．
- 最終reproducerは，任意の2.9.2 binaryをDebian配布由来と誤って表示しないよう，記録したbinaryのSHA256を実行前に必須照合します．この固定版でrun-003を再生成し，4条件すべての結果を再確認しました．
- 0.2 mm設定で窓内supportが11.6 mmとなる観測を，11.8 mmへ合わせるために窓や下面を変更していません．窓外を含む全support最高Zと，固定中央窓の最高Zは別の量です．
- 単純な `model Z−HEIGHT−support Z` を実物のair gapと呼ぶ案は採用していません．名目CAD下面とsupport指令面の差だけを主量として残します．
- run-003の独立raw再監査でも，4条件の全最高support行・最初のmodel行集合，固定profile差，解決設定，28個のmanifest対象bytesが一致しました．full原本29filesをarchiveへ収録しています．
- repo全体の実験testで，公開済みE2E auditorをimportすると，その履歴artifact directoryにPython bytecode cacheが生成され，厳密なartifact一覧検査が失敗しました．定義の読込みをbytecodeを生成しない `runpy.run_path` に変更し，directory不変の回帰testを追加しました．計算方式・窓・設定は変更せず，run-004へ再生成し，独立raw再監査も全成功しました．
- PR reviewのP1指摘により，測定方式が一致していても固定実験の期待値に一致しない実行を成功終了させないよう修正しました．全4条件のsupport面・model role/HEIGHT・coverageを必須gateとし，設定0も明示検査します．意図的にraw G-codeのsupport面を12.1へ変え，両auditorがその値に一致しても，失敗recordを保存して成功summaryを出さない回帰testを追加しました．期待値・窓・slice設定は変更していません．
- run-005で4実sliceを再生成し，全条件の必須gateと独立raw監査が成功しました．別の独立process検証でも，contact0.2のsupport Z11.6→11.65とcontact0のmodel role変更が，それぞれexit1・failure.json・成功summaryなしになりました．
