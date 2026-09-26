# 웹 화면 언어

테마 옆의 언어 선택에서 영어·한국어를 선택한다. 모바일에서는 펼침 메뉴의
테마 옆에 표시된다. 기본값은 영어이며 브라우저의 선호 언어나 기기 화면의
언어 설정과 무관하다. 선택은 해당 브라우저의 `mfnavis_web_language` 쿠키에
1년간 보관한다. 변경 시 페이지를 다시 불러와 메뉴와 본문을 함께 갱신한다.

웹 문구는 Flask-Babel의 요청별 번역을 사용한다. 한국어 번역은
`python/locale/ko/LC_MESSAGES/messages.po`이며 배포 시 같은 위치의 `.mo`도
갱신한다. 동적으로 표시하는 문구는 `MFNavis/web_i18n.py`에서 관리한다.
`N_()`는 번역 추출용 표시이며 요청 전에 번역을 확정하지 않는다.

- 적경·적위, 고도·방위각, 구경·초점 거리·접안렌즈·겉보기 시야를 사용한다.
- GoTo는 자동 도입, transit는 남중, magnitude는 등급으로 표시한다.
- 원본 로그·드라이버 오류·사용자가 입력한 관측지/장비 이름·천체 식별자·
  카탈로그 원문 기록은 번역 대상 UI 문구와 구분하며 원문을 보존한다.
- MFNavis, INDI 등 제품/프로토콜 이름과 국제 단위·파일 형식은 유지한다.

```bash
cd python
.venv/bin/pybabel compile -d locale -l ko
.venv/bin/python -m pytest -q tests/test_web_language.py
```

회귀 검사는 언어 기본값과 허용값, 브라우저별 격리, 페이지별 영문 한글 혼용,
웹 번역 누락·미확정 번역·번역 파일 컴파일 일치, 천문 용어를 확인한다.
브라우저 검증에서는 언어 전환·새로고침·SPA 이동·모바일 배치를 확인한다.
사용자 입력과 외부 카탈로그 원문 자체의 언어를 바꾸지는 않는다.

## 오프라인 한글 글꼴

한글 글꼴이 없는 클라이언트에서도 표시되도록 기존 번들 Sarasa 글꼴에서
한글 음절·자모만 추출한 `python/views/css/mfnavis-korean.woff2`를 제공한다.
폰트 이름은 `MFNavis Korean`이며 웹 페이지에서 한글에만 사용한다.
원저작자 고지는 같은 디렉터리의 `mfnavis-korean.LICENSE.txt`에 있다.

재생성에는 개발 도구 FontTools와 Brotli가 필요하다. 앱 실행에는 필요 없다.

```bash
python -m pip install 'fonttools[woff]'
python scripts/build_web_korean_font.py
```
