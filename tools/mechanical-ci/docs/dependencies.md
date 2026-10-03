# 依存softwareとlicense

dependencyのsource/binaryはこのdirectoryへvendoringしません．主要な依存先は以下です．各softwareの改変・再配布・network提供・他製品との結合では，採用版のlicenseと依存物の条件を別途確認してください．これは全依存物の法的監査ではありません．

## 現在使うもの

- Python標準library: CLI，manifest，G-code解析，process起動
- [CadQuery 2.7.0](https://github.com/CadQuery/cadquery/blob/master/LICENSE): Apache-2.0．geometry extraとして導入
- [Open CASCADE Technology](https://occt3d.com/open-cascade-technology/index.html): LGPL-2.1と追加exception．CadQueryのCAD kernel
- [PrusaSlicer](https://github.com/prusa3d/PrusaSlicer/blob/master/LICENSE): AGPL-3.0．別途導入する実行ファイル．同梱合成manifestは2.9.2で試験

CadQueryのtop-level versionはextraで固定していますが，全推移依存をlockしたcontainerは提供していません．PrusaSlicerはversionを照合し，実行binaryのhashも結果へ記録します．stable versionのbuild suffixは許可し，alpha/beta等のprerelease suffixは拒否します．再現実験ではOS，依存library，profileも固定してください．

## 将来の接続候補

- [Gmsh](https://gmsh.info/): GPL-2.0-or-laterとexception
- [CalculiX](https://www.dhondt.de/): GPL v2系
- [OMPL](https://ompl.kavrakilab.org/license.html)と[FCL](https://github.com/flexible-collision-library/fcl/blob/master/LICENSE): BSD-3-Clause
- [MuJoCo](https://github.com/google-deepmind/mujoco/blob/main/LICENSE): Apache-2.0

これらを今のpackageが自動installしたり呼び出したりすることはありません．Gmsh公式はclosed-source製品への統合・配布についてcommercial licenseが必要となる場合を説明しています．無料で自分のローカル計算を回すことと，任意の条件で再配布できることは同じではありません．

## この新規software

この新規softwareの自作コードは，licenseをまだ選択せずsourceを公開しています．このpackageが依存するOSSのlicenseを，この新規softwareへ自動で適用していません．
