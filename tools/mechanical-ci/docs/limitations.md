# 検証範囲

## 幾何

- checkerは生成コードから独立し，凍結STEPを読込みます．ただしCadQuery/OCCTという同じCAD kernelを使う可能性はあり，別kernelによる独立性を主張しません
- 指定した平行移動経路の離散サンプルだけです．回転，6自由度探索，連続掃引，干渉しない経路の自動発見は未実装です
- 経路未発見や一つの経路の遮断は，完全保持の証明になりません
- 干渉体積は力，応力，ひずみ，必要な解除力ではありません

## G-code

対象はPrusa系の，明示的なmm・絶対XYZ・単一extruder・直線G0/G1です．座標と押出baselineが不明な状態から経路を推測しません．

- G21，G90，M82/M83を明示します．絶対押出にはG92 Eのbaselineが必要です
- 造形移動の前にXYZを確立します．G92によるXYZ offset，relative XYZ，arc，複数tool，volumetric E，flow override，未知のM commandなどは拒否します
- 座標tokenは空白で区切った10進表記のみです．packed commandや指数表記は対象外です
- retractの回復量を押出から除きます．同一移動内の回復/押出は距離に比例すると仮定して分割します
- stationary primeは線分と分けて数えます
- 幅/層高/役割が不足する線分はunknownとして数え，補完しません
- 解析fileは最大64 MiBです．これは汎用のfirmware interpreterやsecurity sandboxではありません

経路はslicerが意図したcommandです．実際の線幅，押出誤差，空隙，層間接着，温度履歴，接触面の粗さを測定したものではありません．supportを出力できても，工具が届く，壊さず除去できる，除去後に機構が動く，とは判定できません．

## 未実装gate

現在の結果には以下を必ず`not_implemented`として含めます．

- `continuous_collision`
- `six_dof_escape_search`
- `support_removal`
- `contact_strength_fem`
- `material_calibration`
- `robot_measurement`

Gmsh/CalculiXへのmesh・材料配向・非線形contact連携は，この公開最小CLIには接続していません．層経路から材料モデルへの変換，mesh収束，実印刷の力–変位校正，creep/fatigueの検証を追加するまで，強度/保持力を保証しません．

## 運用

trustedな入力とsoftwareを，制限した作業環境で使ってください．backend実行ファイル自身の安全性や全依存物をこのCLIが保証することはありません．実機への印刷，robot motion，flash，ネットワーク設定変更はこのCLIのscope外です．大量iterationでソフトの呼出課金は必要ありませんが，計算資源・電力・材料・実験設備の費用は別です．
