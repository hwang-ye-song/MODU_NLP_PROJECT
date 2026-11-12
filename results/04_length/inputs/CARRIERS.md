# 04_length carrier 출처 (Wikipedia, CC BY-SA 4.0)

이 실험의 carrier 텍스트는 영어 위키백과 문서에서 왔습니다. 위키백과 텍스트는 [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) 라이선스이며, 저작자는 각 문서의 기여자들입니다 (각 URL의 '역사' 탭).

- 원본: Hugging Face `wikimedia/wikipedia` 설정 `20231101.en` (2023-11-01 덤프). HF datasets-server rows API, train split, offset 0–180000 (간격 20000), offset마다 100행, 4,000–60,000자 문서만 (`sim/fetch_corpora.py`). 파일 md5 `7b907cf3cd90c26dfe78883746a154d9`.
- **변경 사항**: 참고문헌류 절(See also, References, Notes, Further reading, External links …)부터 뒤를 버렸고, 제목·소제목·목록·표·캡션 줄을 빼고 산문 문단만 남겼습니다. 여러 문서를 빈 줄로 이어 붙였고, 길이별로 문장 끝에서 잘랐습니다. 인젝션 행에는 실험용 지시문 한 문장을 넣었습니다 (위키백과 원문이 아님).
- 각 stream의 문서는 아래 순서대로 이어집니다. `prose chars`는 정리 후 그 문서가 차지하는 글자 수, `first in carrier`는 그 문서가 처음 들어가는 carrier 길이입니다 (64k 밖이면 stream에만 있고 판정 문서에는 없음).

## C01 (span S01, stream 65,013자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | Janet Jackson videography | https://en.wikipedia.org/wiki/Janet%20Jackson%20videography | 8,019 | 2k |
| 2 | Archduke Joseph Ferdinand of Austria | https://en.wikipedia.org/wiki/Archduke%20Joseph%20Ferdinand%20of%20Austria | 4,613 | 16k |
| 3 | Demographics of Angola | https://en.wikipedia.org/wiki/Demographics%20of%20Angola | 6,295 | 16k |
| 4 | Heffley Creek | https://en.wikipedia.org/wiki/Heffley%20Creek | 11,960 | 32k |
| 5 | Alkane | https://en.wikipedia.org/wiki/Alkane | 34,118 | 32k |

## C02 (span S02, stream 65,000자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | Animation | https://en.wikipedia.org/wiki/Animation | 34,637 | 2k |
| 2 | Jefferson J. DeBlanc | https://en.wikipedia.org/wiki/Jefferson%20J.%20DeBlanc | 11,350 | 64k |
| 3 | Raina Telgemeier | https://en.wikipedia.org/wiki/Raina%20Telgemeier | 6,352 | 64k |
| 4 | Star Wars: Episode I – The Phantom Menace (video game) | https://en.wikipedia.org/wiki/Star%20Wars%3A%20Episode%20I%20%E2%80%93%20The%20Phantom%20Menace%20%28video%20game%29 | 8,027 | 64k |
| 5 | Kenyon Coleman | https://en.wikipedia.org/wiki/Kenyon%20Coleman | 4,626 | 64k |

## C03 (span S03, stream 65,782자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | Port security | https://en.wikipedia.org/wiki/Port%20security | 28,611 | 2k |
| 2 | Survivor: Cook Islands | https://en.wikipedia.org/wiki/Survivor%3A%20Cook%20Islands | 8,299 | 32k |
| 3 | Damaru | https://en.wikipedia.org/wiki/Damaru | 6,750 | 64k |
| 4 | Adventure | https://en.wikipedia.org/wiki/Adventure | 3,780 | 64k |
| 5 | Wine of the United States | https://en.wikipedia.org/wiki/Wine%20of%20the%20United%20States | 12,785 | 64k |
| 6 | Defensa y Justicia | https://en.wikipedia.org/wiki/Defensa%20y%20Justicia | 5,547 | 64k |

## C04 (span S04, stream 65,004자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | Marseille-Saint-Charles station | https://en.wikipedia.org/wiki/Marseille-Saint-Charles%20station | 3,167 | 2k |
| 2 | American Football Conference | https://en.wikipedia.org/wiki/American%20Football%20Conference | 7,283 | 4k |
| 3 | Alcázar de los Reyes Cristianos | https://en.wikipedia.org/wiki/Alc%C3%A1zar%20de%20los%20Reyes%20Cristianos | 10,441 | 16k |
| 4 | Ayn Rand | https://en.wikipedia.org/wiki/Ayn%20Rand | 37,886 | 32k |
| 5 | Crichton Castle | https://en.wikipedia.org/wiki/Crichton%20Castle | 6,219 | 64k |

## C05 (span S05, stream 65,406자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | Appellate court | https://en.wikipedia.org/wiki/Appellate%20court | 8,005 | 2k |
| 2 | Moya Henderson | https://en.wikipedia.org/wiki/Moya%20Henderson | 3,583 | 16k |
| 3 | Marzban | https://en.wikipedia.org/wiki/Marzban | 5,969 | 16k |
| 4 | Afroasiatic languages | https://en.wikipedia.org/wiki/Afroasiatic%20languages | 47,843 | 32k |

## C06 (span S06, stream 65,507자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | Nejat Eczacıbaşı | https://en.wikipedia.org/wiki/Nejat%20Eczac%C4%B1ba%C5%9F%C4%B1 | 7,237 | 2k |
| 2 | Arraignment | https://en.wikipedia.org/wiki/Arraignment | 6,277 | 8k |
| 3 | Superman curse | https://en.wikipedia.org/wiki/Superman%20curse | 10,549 | 16k |
| 4 | Agnostida | https://en.wikipedia.org/wiki/Agnostida | 3,621 | 32k |
| 5 | Austroasiatic languages | https://en.wikipedia.org/wiki/Austroasiatic%20languages | 20,471 | 32k |
| 6 | Shaligram | https://en.wikipedia.org/wiki/Shaligram | 17,342 | 64k |

## C07 (span S07, stream 65,029자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | Alexander Asboth | https://en.wikipedia.org/wiki/Alexander%20Asboth | 2,799 | 2k |
| 2 | Humanism | https://en.wikipedia.org/wiki/Humanism | 42,624 | 4k |
| 3 | Charlie Cox | https://en.wikipedia.org/wiki/Charlie%20Cox | 8,175 | 64k |
| 4 | 17 | https://en.wikipedia.org/wiki/Nanaka%206/17 | 6,476 | 64k |
| 5 | Star Wars: Republic | https://en.wikipedia.org/wiki/Star%20Wars%3A%20Republic | 4,947 | 64k |

## C08 (span S08, stream 65,179자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | Yeronga Memorial Park | https://en.wikipedia.org/wiki/Yeronga%20Memorial%20Park | 24,259 | 2k |
| 2 | The Island of Dr. Moreau (1977 film) | https://en.wikipedia.org/wiki/The%20Island%20of%20Dr.%20Moreau%20%281977%20film%29 | 7,761 | 32k |
| 3 | Oleg Grabar | https://en.wikipedia.org/wiki/Oleg%20Grabar | 3,427 | 64k |
| 4 | WLOV-TV | https://en.wikipedia.org/wiki/WLOV-TV | 5,833 | 64k |
| 5 | Adobe | https://en.wikipedia.org/wiki/Adobe | 14,599 | 64k |
| 6 | Muconate lactonizing enzyme | https://en.wikipedia.org/wiki/Muconate%20lactonizing%20enzyme | 9,290 | 64k |

## C09 (span S09, stream 65,041자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | Alphabet | https://en.wikipedia.org/wiki/Alphabet | 26,591 | 2k |
| 2 | Gentlemen and Players (TV series) | https://en.wikipedia.org/wiki/Gentlemen%20and%20Players%20%28TV%20series%29 | 3,174 | 32k |
| 3 | St. Paul's Cathedral, Kolkata | https://en.wikipedia.org/wiki/St.%20Paul%27s%20Cathedral%2C%20Kolkata | 9,131 | 32k |
| 4 | United Macedonia | https://en.wikipedia.org/wiki/United%20Macedonia | 5,392 | 64k |
| 5 | R. C. Sproul Jr. | https://en.wikipedia.org/wiki/R.%20C.%20Sproul%20Jr. | 6,737 | 64k |
| 6 | Karo people (Indonesia) | https://en.wikipedia.org/wiki/Karo%20people%20%28Indonesia%29 | 14,006 | 64k |

## C10 (span S10, stream 65,004자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | Xlendi | https://en.wikipedia.org/wiki/Xlendi | 6,670 | 2k |
| 2 | Elemental Masters | https://en.wikipedia.org/wiki/Elemental%20Masters | 5,507 | 8k |
| 3 | Anthropology | https://en.wikipedia.org/wiki/Anthropology | 49,786 | 16k |
| 4 | Dan Roundfield | https://en.wikipedia.org/wiki/Dan%20Roundfield | 3,035 | 64k |

## C11 (span S11, stream 65,016자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | Dermacentor variabilis | https://en.wikipedia.org/wiki/Dermacentor%20variabilis | 6,657 | 2k |
| 2 | South Lancaster Academy | https://en.wikipedia.org/wiki/South%20Lancaster%20Academy | 3,072 | 8k |
| 3 | John H. Hall (gunsmith) | https://en.wikipedia.org/wiki/John%20H.%20Hall%20%28gunsmith%29 | 5,474 | 16k |
| 4 | Atlantic Ocean | https://en.wikipedia.org/wiki/Atlantic%20Ocean | 49,807 | 16k |

## C12 (span S12, stream 66,113자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | American National Standards Institute | https://en.wikipedia.org/wiki/American%20National%20Standards%20Institute | 8,150 | 2k |
| 2 | Reema Lagoo | https://en.wikipedia.org/wiki/Reema%20Lagoo | 4,842 | 16k |
| 3 | Anarchism | https://en.wikipedia.org/wiki/Anarchism | 44,867 | 16k |
| 4 | Nicolas Chédeville | https://en.wikipedia.org/wiki/Nicolas%20Ch%C3%A9deville | 6,397 | 64k |
| 5 | The Arrows (Canadian band) | https://en.wikipedia.org/wiki/The%20Arrows%20%28Canadian%20band%29 | 1,849 | – (64k 밖) |

## C13 (span S13, stream 65,002자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | University of the Basque Country | https://en.wikipedia.org/wiki/University%20of%20the%20Basque%20Country | 6,288 | 2k |
| 2 | Albert Sidney Johnston | https://en.wikipedia.org/wiki/Albert%20Sidney%20Johnston | 34,276 | 8k |
| 3 | Three points for a win | https://en.wikipedia.org/wiki/Three%20points%20for%20a%20win | 8,015 | 64k |
| 4 | 2000 American League Championship Series | https://en.wikipedia.org/wiki/2000%20American%20League%20Championship%20Series | 11,903 | 64k |
| 5 | Batter's eye | https://en.wikipedia.org/wiki/Batter%27s%20eye | 4,512 | 64k |

## C14 (span S14, stream 65,289자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | Nagasaki Peace Park | https://en.wikipedia.org/wiki/Nagasaki%20Peace%20Park | 7,119 | 2k |
| 2 | Dean Heritage Centre | https://en.wikipedia.org/wiki/Dean%20Heritage%20Centre | 5,561 | 8k |
| 3 | Josh Caterer | https://en.wikipedia.org/wiki/Josh%20Caterer | 3,511 | 16k |
| 4 | Andre Agassi | https://en.wikipedia.org/wiki/Andre%20Agassi | 49,092 | 32k |

## C15 (span S15, stream 65,001자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | Aldous Huxley | https://en.wikipedia.org/wiki/Aldous%20Huxley | 19,444 | 2k |
| 2 | MLB on Five | https://en.wikipedia.org/wiki/MLB%20on%20Five | 9,356 | 32k |
| 3 | Brian Viloria | https://en.wikipedia.org/wiki/Brian%20Viloria | 5,563 | 32k |
| 4 | Mac Maharaj | https://en.wikipedia.org/wiki/Mac%20Maharaj | 3,481 | 64k |
| 5 | Charlie Sexton | https://en.wikipedia.org/wiki/Charlie%20Sexton | 7,749 | 64k |
| 6 | Aardvark | https://en.wikipedia.org/wiki/Aardvark | 19,398 | 64k |

## C16 (span S16, stream 65,245자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | International Atomic Time | https://en.wikipedia.org/wiki/International%20Atomic%20Time | 7,011 | 2k |
| 2 | NDTV 24x7 | https://en.wikipedia.org/wiki/NDTV%2024x7 | 8,450 | 8k |
| 3 | Patrick Wallace | https://en.wikipedia.org/wiki/Patrick%20Wallace | 5,075 | 16k |
| 4 | Alain Connes | https://en.wikipedia.org/wiki/Alain%20Connes | 3,478 | 32k |
| 5 | OT VIII | https://en.wikipedia.org/wiki/OT%20VIII | 13,301 | 32k |
| 6 | Analysis of variance | https://en.wikipedia.org/wiki/Analysis%20of%20variance | 27,920 | 64k |

## C17 (span S17, stream 65,002자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | Hellenic College Holy Cross Greek Orthodox School of Theology | https://en.wikipedia.org/wiki/Hellenic%20College%20Holy%20Cross%20Greek%20Orthodox%20School%20of%20Theology | 3,113 | 2k |
| 2 | The Second Summer of the Sisterhood | https://en.wikipedia.org/wiki/The%20Second%20Summer%20of%20the%20Sisterhood | 10,596 | 4k |
| 3 | Economy of Angola | https://en.wikipedia.org/wiki/Economy%20of%20Angola | 17,240 | 16k |
| 4 | Vermont Route 15 | https://en.wikipedia.org/wiki/Vermont%20Route%2015 | 6,284 | 32k |
| 5 | United States African Development Foundation | https://en.wikipedia.org/wiki/United%20States%20African%20Development%20Foundation | 20,544 | 64k |
| 6 | Current clamp | https://en.wikipedia.org/wiki/Current%20clamp | 7,215 | 64k |

## C18 (span S18, stream 65,002자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | Post–World War II Sherman tanks | https://en.wikipedia.org/wiki/Post%E2%80%93World%20War%20II%20Sherman%20tanks | 28,307 | 2k |
| 2 | Tara (Northern Ireland) | https://en.wikipedia.org/wiki/Tara%20%28Northern%20Ireland%29 | 7,013 | 32k |
| 3 | CPA (agriculture) | https://en.wikipedia.org/wiki/CPA%20%28agriculture%29 | 3,199 | 64k |
| 4 | Charles M. Schulz–Sonoma County Airport | https://en.wikipedia.org/wiki/Charles%20M.%20Schulz%E2%80%93Sonoma%20County%20Airport | 13,090 | 64k |
| 5 | Tunde Jegede | https://en.wikipedia.org/wiki/Tunde%20Jegede | 5,130 | 64k |
| 6 | New York State Route 383 | https://en.wikipedia.org/wiki/New%20York%20State%20Route%20383 | 8,253 | 64k |

## C19 (span S19, stream 65,029자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | Agricultural science | https://en.wikipedia.org/wiki/Agricultural%20science | 2,454 | 2k |
| 2 | The Mall Athens | https://en.wikipedia.org/wiki/The%20Mall%20Athens | 6,436 | 4k |
| 3 | Scouts' Day | https://en.wikipedia.org/wiki/Scouts%27%20Day | 4,846 | 16k |
| 4 | Bitumen | https://en.wikipedia.org/wiki/Bitumen | 51,287 | 16k |

## C20 (span S20, stream 65,581자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | Regis College (Massachusetts) | https://en.wikipedia.org/wiki/Regis%20College%20%28Massachusetts%29 | 6,090 | 2k |
| 2 | Kiritsugu Emiya | https://en.wikipedia.org/wiki/Kiritsugu%20Emiya | 15,848 | 8k |
| 3 | The Straps | https://en.wikipedia.org/wiki/The%20Straps | 3,674 | 32k |
| 4 | A | https://en.wikipedia.org/wiki/A | 7,517 | 32k |
| 5 | Devolved (band) | https://en.wikipedia.org/wiki/Devolved%20%28band%29 | 10,136 | 64k |
| 6 | Albedo | https://en.wikipedia.org/wiki/Albedo | 22,306 | 64k |

## C21 (span S21, stream 65,067자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | Algae | https://en.wikipedia.org/wiki/Algae | 26,283 | 2k |
| 2 | Hinduism and Sikhism | https://en.wikipedia.org/wiki/Hinduism%20and%20Sikhism | 14,453 | 32k |
| 3 | Nicola Stapleton | https://en.wikipedia.org/wiki/Nicola%20Stapleton | 9,121 | 64k |
| 4 | Battle of Djerba | https://en.wikipedia.org/wiki/Battle%20of%20Djerba | 6,637 | 64k |
| 5 | Pahlavas | https://en.wikipedia.org/wiki/Pahlavas | 5,241 | 64k |
| 6 | Styl Kar | https://en.wikipedia.org/wiki/Styl%20Kar | 3,322 | 64k |

## C22 (span S22, stream 65,000자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | Andrea Beaumont | https://en.wikipedia.org/wiki/Andrea%20Beaumont | 18,306 | 2k |
| 2 | Saskatchewan Accelerator Laboratory | https://en.wikipedia.org/wiki/Saskatchewan%20Accelerator%20Laboratory | 6,175 | 32k |
| 3 | Blue Hill Meteorological Observatory | https://en.wikipedia.org/wiki/Blue%20Hill%20Meteorological%20Observatory | 10,369 | 32k |
| 4 | Marco Uccellini | https://en.wikipedia.org/wiki/Marco%20Uccellini | 3,190 | 64k |
| 5 | Companions of the Cross | https://en.wikipedia.org/wiki/Companions%20of%20the%20Cross | 7,187 | 64k |
| 6 | Hitchin Boys' School | https://en.wikipedia.org/wiki/Hitchin%20Boys%27%20School | 19,763 | 64k |

## C23 (span S23, stream 65,351자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | Arithmetic mean | https://en.wikipedia.org/wiki/Arithmetic%20mean | 7,767 | 2k |
| 2 | John Lundberg | https://en.wikipedia.org/wiki/John%20Lundberg | 3,554 | 8k |
| 3 | Atomic number | https://en.wikipedia.org/wiki/Atomic%20number | 9,812 | 16k |
| 4 | Gorlice–Tarnów offensive | https://en.wikipedia.org/wiki/Gorlice%E2%80%93Tarn%C3%B3w%20offensive | 21,424 | 32k |
| 5 | Star Wars: Episode I – The Phantom Menace (soundtrack) | https://en.wikipedia.org/wiki/Star%20Wars%3A%20Episode%20I%20%E2%80%93%20The%20Phantom%20Menace%20%28soundtrack%29 | 5,888 | 64k |
| 6 | Flight of the Intruder | https://en.wikipedia.org/wiki/Flight%20of%20the%20Intruder | 16,896 | 64k |

## C24 (span S24, stream 65,538자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | Energy Policy and Conservation Act | https://en.wikipedia.org/wiki/Energy%20Policy%20and%20Conservation%20Act | 6,140 | 2k |
| 2 | Elizabeth Peyton | https://en.wikipedia.org/wiki/Elizabeth%20Peyton | 9,505 | 8k |
| 3 | WSCV | https://en.wikipedia.org/wiki/WSCV | 14,902 | 16k |
| 4 | Astronaut | https://en.wikipedia.org/wiki/Astronaut | 23,898 | 32k |
| 5 | Tom Howard (musician) | https://en.wikipedia.org/wiki/Tom%20Howard%20%28musician%29 | 7,450 | 64k |
| 6 | Cornelius Stirk | https://en.wikipedia.org/wiki/Cornelius%20Stirk | 3,633 | 64k |

## C25 (span S25, stream 65,154자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | Confederation of Labour Podkrepa | https://en.wikipedia.org/wiki/Confederation%20of%20Labour%20Podkrepa | 4,844 | 2k |
| 2 | Canungra, Queensland | https://en.wikipedia.org/wiki/Canungra%2C%20Queensland | 8,151 | 8k |
| 3 | Moose Jaw Canucks | https://en.wikipedia.org/wiki/Moose%20Jaw%20Canucks | 2,340 | 16k |
| 4 | Woo Bum-kon | https://en.wikipedia.org/wiki/Woo%20Bum-kon | 6,426 | 16k |
| 5 | 70th Infantry Division (United Kingdom) | https://en.wikipedia.org/wiki/70th%20Infantry%20Division%20%28United%20Kingdom%29 | 31,066 | 32k |
| 6 | Soups in East Asian culture | https://en.wikipedia.org/wiki/Soups%20in%20East%20Asian%20culture | 12,317 | 64k |

## C26 (span S26, stream 65,765자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | Kragujevac massacre | https://en.wikipedia.org/wiki/Kragujevac%20massacre | 29,835 | 2k |
| 2 | Xianning | https://en.wikipedia.org/wiki/Xianning | 5,015 | 32k |
| 3 | Politics of Angola | https://en.wikipedia.org/wiki/Politics%20of%20Angola | 6,486 | 64k |
| 4 | Durbanville | https://en.wikipedia.org/wiki/Durbanville | 12,398 | 64k |
| 5 | Academy of Performing Arts in Prague | https://en.wikipedia.org/wiki/Academy%20of%20Performing%20Arts%20in%20Prague | 8,244 | 64k |
| 6 | Rongbuk Monastery | https://en.wikipedia.org/wiki/Rongbuk%20Monastery | 3,777 | 64k |

## C27 (span S27, stream 65,343자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | Carlo Caffarra | https://en.wikipedia.org/wiki/Carlo%20Caffarra | 5,234 | 2k |
| 2 | Aruba | https://en.wikipedia.org/wiki/Aruba | 56,558 | 8k |
| 3 | Rolling code | https://en.wikipedia.org/wiki/Rolling%20code | 3,547 | 64k |

## C28 (span S28, stream 65,368자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | Don McMahon | https://en.wikipedia.org/wiki/Don%20McMahon | 3,556 | 2k |
| 2 | Aluminum Corporation of China Limited | https://en.wikipedia.org/wiki/Aluminum%20Corporation%20of%20China%20Limited | 6,158 | 4k |
| 3 | Asia | https://en.wikipedia.org/wiki/Asia | 38,282 | 16k |
| 4 | Hyperekplexia | https://en.wikipedia.org/wiki/Hyperekplexia | 7,332 | 64k |
| 5 | America the Beautiful | https://en.wikipedia.org/wiki/America%20the%20Beautiful | 10,032 | 64k |

## C29 (span S29, stream 65,101자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | Kubitzki system | https://en.wikipedia.org/wiki/Kubitzki%20system | 2,622 | 2k |
| 2 | Nathaniel Green Taylor | https://en.wikipedia.org/wiki/Nathaniel%20Green%20Taylor | 4,886 | 4k |
| 3 | Alchemy | https://en.wikipedia.org/wiki/Alchemy | 51,125 | 8k |
| 4 | Critical geography | https://en.wikipedia.org/wiki/Critical%20geography | 6,462 | 64k |

## C30 (span S30, stream 65,054자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | Ali Zafar | https://en.wikipedia.org/wiki/Ali%20Zafar | 15,008 | 2k |
| 2 | Roman military personal equipment | https://en.wikipedia.org/wiki/Roman%20military%20personal%20equipment | 22,894 | 16k |
| 3 | Anthony Lerew | https://en.wikipedia.org/wiki/Anthony%20Lerew | 3,408 | 64k |
| 4 | Horace Mann Bond | https://en.wikipedia.org/wiki/Horace%20Mann%20Bond | 10,385 | 64k |
| 5 | AGBU Manoogian-Demirdjian School | https://en.wikipedia.org/wiki/AGBU%20Manoogian-Demirdjian%20School | 7,655 | 64k |
| 6 | Josiah Gorgas | https://en.wikipedia.org/wiki/Josiah%20Gorgas | 5,694 | 64k |

## C31 (span S31, stream 65,331자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | AutoPulse | https://en.wikipedia.org/wiki/AutoPulse | 5,916 | 2k |
| 2 | Devotional medal | https://en.wikipedia.org/wiki/Devotional%20medal | 15,765 | 8k |
| 3 | Georgia State Route 16 | https://en.wikipedia.org/wiki/Georgia%20State%20Route%2016 | 7,789 | 32k |
| 4 | Canadian Electroacoustic Community | https://en.wikipedia.org/wiki/Canadian%20Electroacoustic%20Community | 9,746 | 32k |
| 5 | Abacus | https://en.wikipedia.org/wiki/Abacus | 22,565 | 64k |
| 6 | A Dirty Job | https://en.wikipedia.org/wiki/A%20Dirty%20Job | 3,540 | 64k |

## C32 (span S32, stream 65,371자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | The Symbolic | https://en.wikipedia.org/wiki/The%20Symbolic | 6,360 | 2k |
| 2 | Chris Canty (defensive lineman) | https://en.wikipedia.org/wiki/Chris%20Canty%20%28defensive%20lineman%29 | 8,039 | 8k |
| 3 | Academy Awards | https://en.wikipedia.org/wiki/Academy%20Awards | 45,091 | 16k |
| 4 | Plaza Mayor, Madrid | https://en.wikipedia.org/wiki/Plaza%20Mayor%2C%20Madrid | 4,695 | 64k |
| 5 | 14th Infantry Brigade (United Kingdom) | https://en.wikipedia.org/wiki/14th%20Infantry%20Brigade%20%28United%20Kingdom%29 | 1,178 | – (64k 밖) |

## C33 (span S33, stream 65,021자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | Ammunition technical officer | https://en.wikipedia.org/wiki/Ammunition%20technical%20officer | 7,843 | 2k |
| 2 | Merilyn Simonds | https://en.wikipedia.org/wiki/Merilyn%20Simonds | 3,289 | 8k |
| 3 | The Imaginary (psychoanalysis) | https://en.wikipedia.org/wiki/The%20Imaginary%20%28psychoanalysis%29 | 5,808 | 16k |
| 4 | Irish Free State offensive | https://en.wikipedia.org/wiki/Irish%20Free%20State%20offensive | 16,552 | 32k |
| 5 | Angolan Armed Forces | https://en.wikipedia.org/wiki/Angolan%20Armed%20Forces | 9,551 | 64k |
| 6 | Globally Harmonized System of Classification and Labelling of Chemicals | https://en.wikipedia.org/wiki/Globally%20Harmonized%20System%20of%20Classification%20and%20Labelling%20of%20Chemicals | 21,968 | 64k |

## C34 (span S34, stream 65,310자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | Allah | https://en.wikipedia.org/wiki/Allah | 14,646 | 2k |
| 2 | WDVM-TV | https://en.wikipedia.org/wiki/WDVM-TV | 9,452 | 16k |
| 3 | 376th Air Expeditionary Wing | https://en.wikipedia.org/wiki/376th%20Air%20Expeditionary%20Wing | 7,615 | 32k |
| 4 | Re-Mission | https://en.wikipedia.org/wiki/Re-Mission | 5,864 | 32k |
| 5 | Diana Douglas | https://en.wikipedia.org/wiki/Diana%20Douglas | 3,531 | 64k |
| 6 | Aikido | https://en.wikipedia.org/wiki/Aikido | 24,192 | 64k |

## C35 (span S35, stream 65,154자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | Orlando Brown (actor) | https://en.wikipedia.org/wiki/Orlando%20Brown%20%28actor%29 | 5,257 | 2k |
| 2 | Actinopterygii | https://en.wikipedia.org/wiki/Actinopterygii | 6,698 | 8k |
| 3 | Bennettsbridge | https://en.wikipedia.org/wiki/Bennettsbridge | 3,408 | 16k |
| 4 | Frieda Fromm-Reichmann | https://en.wikipedia.org/wiki/Frieda%20Fromm-Reichmann | 13,746 | 16k |
| 5 | Seafort Saga | https://en.wikipedia.org/wiki/Seafort%20Saga | 27,081 | 32k |
| 6 | Park Theatre (Manhattan) | https://en.wikipedia.org/wiki/Park%20Theatre%20%28Manhattan%29 | 8,954 | 64k |

## C36 (span S36, stream 65,021자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | Louis de Caullery | https://en.wikipedia.org/wiki/Louis%20de%20Caullery | 5,368 | 2k |
| 2 | Great White Shark (character) | https://en.wikipedia.org/wiki/Great%20White%20Shark%20%28character%29 | 6,710 | 8k |
| 3 | Acid | https://en.wikipedia.org/wiki/Acid | 26,360 | 16k |
| 4 | Cockfighter | https://en.wikipedia.org/wiki/Cockfighter | 3,173 | 64k |
| 5 | Little Eaton | https://en.wikipedia.org/wiki/Little%20Eaton | 8,966 | 64k |
| 6 | The Real | https://en.wikipedia.org/wiki/The%20Real | 14,434 | 64k |

## C37 (span S37, stream 65,736자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | Trevor Kidd | https://en.wikipedia.org/wiki/Trevor%20Kidd | 3,749 | 2k |
| 2 | Kykkos Monastery | https://en.wikipedia.org/wiki/Kykkos%20Monastery | 6,500 | 4k |
| 3 | Homenetmen | https://en.wikipedia.org/wiki/Homenetmen | 5,060 | 16k |
| 4 | ASCII | https://en.wikipedia.org/wiki/ASCII | 29,727 | 16k |
| 5 | James Mullins (American politician) | https://en.wikipedia.org/wiki/James%20Mullins%20%28American%20politician%29 | 8,249 | 64k |
| 6 | Doedicurus | https://en.wikipedia.org/wiki/Doedicurus | 12,441 | 64k |

## C38 (span S38, stream 65,336자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | Jimmy Sexton | https://en.wikipedia.org/wiki/Jimmy%20Sexton | 5,894 | 2k |
| 2 | Woolf Barnato | https://en.wikipedia.org/wiki/Woolf%20Barnato | 10,761 | 8k |
| 3 | Articles of Confederation | https://en.wikipedia.org/wiki/Articles%20of%20Confederation | 37,222 | 32k |
| 4 | Buttevant Franciscan Friary | https://en.wikipedia.org/wiki/Buttevant%20Franciscan%20Friary | 7,909 | 64k |
| 5 | Mark Bryan | https://en.wikipedia.org/wiki/Mark%20Bryan | 3,542 | 64k |

## C39 (span S39, stream 65,001자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | Crosstown Expressway (Chicago) | https://en.wikipedia.org/wiki/Crosstown%20Expressway%20%28Chicago%29 | 5,726 | 2k |
| 2 | Gloucester Park, Perth | https://en.wikipedia.org/wiki/Gloucester%20Park%2C%20Perth | 7,881 | 8k |
| 3 | Amateur astronomy | https://en.wikipedia.org/wiki/Amateur%20astronomy | 21,620 | 16k |
| 4 | Biosys | https://en.wikipedia.org/wiki/Biosys | 16,750 | 64k |
| 5 | Leo Fortune-West | https://en.wikipedia.org/wiki/Leo%20Fortune-West | 9,665 | 64k |
| 6 | Jelena Dimitrijević | https://en.wikipedia.org/wiki/Jelena%20Dimitrijevi%C4%87 | 3,349 | 64k |

## C40 (span S40, stream 65,641자)

| # | 제목 | URL | prose chars | first in carrier |
| --- | --- | --- | --- | --- |
| 1 | The Official Encyclopedia of Bridge | https://en.wikipedia.org/wiki/The%20Official%20Encyclopedia%20of%20Bridge | 7,924 | 2k |
| 2 | John W. Jones (ex-slave) | https://en.wikipedia.org/wiki/John%20W.%20Jones%20%28ex-slave%29 | 6,137 | 8k |
| 3 | Aardwolf | https://en.wikipedia.org/wiki/Aardwolf | 11,309 | 16k |
| 4 | History of molecular biology | https://en.wikipedia.org/wiki/History%20of%20molecular%20biology | 36,572 | 32k |
| 5 | The Dust Factory | https://en.wikipedia.org/wiki/The%20Dust%20Factory | 3,691 | 64k |
