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
- Eのbaseline，差分，retract debtは，入力10進tokenから作る厳密な有理数で管理します．G92 Eのresetでも未回復debtを維持し，絶対Eの丸め差から偽の微小primeを作りません．epsilonで微小な正の押出を消す処理は行いません
- E tokenは最大4096文字，Eの絶対値と内部累積は有限floatの範囲内です．出力はJSONのfloatへ変換するため，正の押出量が0へunderflowする場合や，mixed unretractの移動区間が端点へ丸め潰れる場合は入力エラーにします．XYZ，線幅，層高，経路の座標演算全体を厳密化したものではありません
- stationary primeは線分と分けて数えます
- 幅/層高/役割が不足する線分はunknownとして数え，補完しません
- 解析fileは最大64 MiBです．これは汎用のfirmware interpreterやsecurity sandboxではありません

経路はslicerが意図したcommandです．実際の線幅，押出誤差，空隙，層間接着，温度履歴，接触面の粗さを測定したものではありません．supportを出力できても，工具が届く，壊さず除去できる，除去後に機構が動く，とは判定できません．

## スライス入力の結び付け

- manifestは1回読んだ同じUTF-8 byte bufferからJSONを解析し，SHA256を計算します．その後のlive fileが不変であるという保証ではありません
- `slice` はversion照会の前に，profile INIとprint STLをprivateな一時directoryへコピーし，同じ読込byteのSHA256をmanifestと照合します．元fileはslicerへ渡しません．basenameは維持します
- 危険なpost-processやnetwork/secret設定の検査対象は，コピーしたINIです．検査後，version照会後，backend終了後，G-code解析後にもsnapshotのhashを確認します
- 元fileがsnapshot作成後に編集・削除されても，照合済みcopyで処理できます．persistentなsnapshot改変は成功扱いにしません．同じuser権限の悪意あるprocessがsnapshotを書き換えて元へ戻す攻撃を防ぐsecurity sandboxではありません
- INIは1 MiB，STLとG-codeはそれぞれ64 MiBまでです．空fileは拒否します．入力snapshotは終了時に削除します
- `input_sha256` は従来どおりmanifestのartifact宣言，`consumed_input_sha256` は実際に渡したINI/STLのhashです．`input_binding=verified_private_snapshots` はこの範囲の結び付けを表します．CAD姿勢や物理性能の検証を追加するものではありません
- G-codeは1つのbyte bufferを解析・hash化し，同じ内容を保存します．全gateの後に，同一filesystem上のhard linkで完成fileを排他的に公開するため，途中で作られた既存outputを上書きしません．対応filesystemが必要です．失敗時は一時生成物を除去し，backendのlocal logがある場合は診断用に残します

実行backendは信頼できるものを使用してください．この入力対策が，slicer自身やその全依存libraryの安全性・実行中の不変性を保証するものではありません．

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
