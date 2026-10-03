# Mechanical CI experiments

対話中の検証から得た方法・失敗知見を，小さな再現実験として共有します．現在のCLIへ統合されたpipelineではありません．自作sourceのlicenseは未選定です．依存softwareのlicenseは変更しません．

## 公開範囲

- [Escape search](escape-search/README.md): 合成STEPの連結6自由度mesh探索と，選択経路の独立BRep再生
- [Frame compliance](frame-compliance/README.md): 合成U-frameの小荷重線形FEMと，支持条件による剛性の差
- [検証から得た知見](lessons.md): 何を調べても，どこから先は未確認のままか

公開fixtureはこの実験用に作った単純形状です．製品CAD，写真，実機profile，実験時の私的path，製品固有の数値・raw dataを含みません．各実験の生成script，依存版，コマンド，合成結果と限界を一緒に置きます．

## 再現できることと追加入力が要ること

合成実験はprivate inputなしで再実行できます．実部品を調べるには，独立に凍結したCAD，単位・座標・組立姿勢，実際の荷重/支持/接触条件，材料校正，印刷条件，現物試験が別途必要です．合成結果の数値を実部品の保持力へ転用できません．

実験の完走，回帰テスト成功，solverの正常終了はそれぞれの限定された計算の成立を示します．設計が印刷できること，組み付くこと，所要荷重で保持することを一括で判定するgateはありません．既存`tools/mechanical-ci`のPR #6で見送った2件のP2（mode行の余分な引数とCAD Boolean例外の扱い）も，本変更では修正していません．

`manifest.json`は公開source・test・結果のSHA-256と，実験の入出力および適用範囲を結び付ける簡単なindexです．Karteやworkerへ接続する実装は含みません．

## 実行とCI

各directoryのREADMEに実行方法があります．GitHub Actionsは合成STEP探索/再生とFEM deck/parser等の軽量testを実行します．Gmsh/CalculiXによる完全なFEM実行は外部実行ファイルを指定する別コマンドです．ローカルで実solverを使った結果と，CIで走るtestを混同しません．第三者binaryは同梱しません．
