# SEP를 최종 비상 복구로 제한 — 2026-09-17

## 판단 근거

현재 보관된 MFDS 적용 후 비교에서 **SEP가 필수인 조건은 확인되지 않았다**.
일부 RMSE·좌표 산포에서 SEP가 유리했지만 최신 MF4p의 복구 불가능한 실패를
SEP만 해결한 필수 사례라는 근거는 아니다. 모든 관측 조건의 우열을 입증한
결론도 아니다.

- `MFDS/docs/test_cedar_free_20260915/MF_PRIMARY_RESULTS_ko.md`: MF4p는 독립
  검증 RAW·전처리 각각 119/119 성공. 구름 RAW는 0/102였지만 전처리에서
  102/102 복구했고, 이 실영상 비교의 SEP 호출은 0회였다.
- 같은 경로 `SPEED_RESULTS_ko.md`: 23장 비교에서 MF4p와 SEP를 끈 MF4p는
  RAW·전처리 모두 23/23. SEP 단독은 RAW 22/23, 전처리 23/23이었다.
- `MOON_CITY_DIAGNOSIS_RESULTS_ko.md`: 달·도심 장면에서 MF4p/MF2/SEP 모두
  RAW 0/24, 전처리 0/22. 영역 제외 후 최초 성공은 MF가 직접 검출한 별로
  이루어졌으며 SEP 추가 호출은 없었다.
- 9월 16일 맑은 하늘 실패 재생 기록에서도 SEP 교체는 대표 3장 모두
  복구하지 못했고, 실제 원인은 밝은 별에 대한 포화 제외였다.

기존 기록을 검토한 것이며 이번 변경으로 새로운 하늘 비교 관측을 수행하지는
않았다. SEP 라이브러리·비교 도구·프로젝트 소유 공통 좌표 필터는 보존한다.

## 운영 정책

1. 실제 solver 시작 시 `PIFINDER_DETECTOR=mf`,
   `MF_DETECT_SEP_FALLBACK=0`을 설정한다. RAW·타일·동기/비동기 전처리의
   정상 검출은 MFDS만 사용한다. 후보 부족이나 native 오류만으로 SEP를
   즉시 호출하지 않는다. 별도 오프라인 비교 도구의 환경 선택은 유지한다.
2. 정상 솔빙 경로가 모두 실패한 정지 프레임에 한해서 SEP를 시도한다.
   MFDS의 품질 통과 후보가 연속성 확인을 기다리는 경우는 실패로 취급하지
   않으며, SEP를 같은 프레임의 독립 확인으로 사용하지 않는다.
3. 같은 프레임의 동기 전처리 결과가 있으면 이를 SEP로 재검출하고, 실패 시
   남은 예산 안에서 RAW를 시도한다. 전처리를 다시 계산하지 않는다.
   이전 프레임의 비동기 결과를 현재 프레임에 붙이지 않는다.
4. 이동 중, RAW가 15초보다 오래됐거나 프레임 ID가 불일치하는 경우는
   비상 검출을 생략한다. 전처리 우선 최적화가 RAW 솔빙을 생략한 프레임도
   SEP를 생략하고, 다음 새 프레임의 MFDS 전체 경로를 먼저 거친다.
5. 비상 단계의 Tetra3 검색 예산은 합계 1000ms다. 검출/전처리/IPC를 포함한
   전체 지연 상한은 아니다. 반복 실패 시 다음 2·4·8개의 실패 프레임을
   건너뛴다. MFDS 성공 시 대기를 초기화한다.
6. 비상 결과에도 기존 좌표 변환·품질·지평선 필터 및 최종 연속성 검사를
   적용한다. 성공한 프레임의 검출 backend와 비상 사용 이유를 보존한다.

`solver_sep_emergency`의 기본값은 `true`다. `false`로 설정하면 최종 비상
SEP도 실행하지 않는다. 적용은 서비스 재시작 시 이루어진다.

`solver_sep_fallback`, `SepShadowRunner`, `sep_full` 등의 기존 이름은 MFDS
전체 프레임 경로에도 쓰이는 호환용 이름이다. 이를 SEP 실행 증거로 해석하거나
`solver_sep_fallback=false`로 전체 프레임 MFDS 경로까지 끄지 않는다.
실제 backend 및 `all_mfds_solve_paths_failed` 사유와
`SEP emergency retry after MFDS failure` 로그를 확인한다.

## 변경·검증

PiFinder의 solver 정책과 runner만 변경했다. 고정 MFDS 바이너리 패키지와
설치 해시는 변경하지 않았다. 앞선 GOTO 표시 변경도 보존했다.

관련 테스트 **168개 통과**(새 회귀 15개), 변경 파일 Ruff 검사·포맷 검사,
`git diff --check` 통과. 정상·후보 부족·native 오류에서 SEP 조기 호출 없음,
최종 실패 복구, MFDS 성공·확인 대기 중 미호출, 프레임 불일치/이동/만료 차단,
전처리→RAW 순서, 실패 대기 및 성공 후 재활성화, 기존 품질·연속성 검사를
검증했다. 기존 Tetra3의 `np.math` 폐기 예정 경고 8건은 남아 있다.

```bash
cd /home/pifinder/PiFinder/python
.venv/bin/python -m pytest -q \
  tests/test_solver_sep_emergency.py tests/test_sep_shadow.py \
  tests/test_sep_fullframe_solve.py tests/test_solver_preprocessed_candidates.py \
  tests/test_solver_scheduling.py tests/test_solver_frame_pairing.py \
  tests/test_solve_acceptance.py tests/test_mf_wide_solver.py \
  tests/test_solver_fullframe.py tests/test_preprocess_bias.py \
  tests/test_solver_capture.py
```

소스 수정과 자동 검증까지 수행했다. 실제 서비스 재시작과 하늘 관측은
수행하지 않았으며, 실행 중 서비스에 반영됐다고 주장하지 않는다.
