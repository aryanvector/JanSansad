# Rajya Sabha people and biography parity

Rajya Sabha Q&A now offers **People behind this record**, alongside the existing
PDF-document check. Debate cards offer **People in this debate**. The shared
bill-presenter card also supports members with a Rajya Sabha profile.

Verified identities can show an official portrait, party, state, official source
link, education, birth date and political-career/positions timeline. No model
generates these details. No contact/address fields are exposed by the new API.

## Official sources

- https://sansad.in/api_rs/member/member-list — current/former-member identities;
  2,547 entries returned during verification on 25 October 2026.
- https://rsdoc.nic.in/MemberGetData/getmemberall — sitting-member state/portrait metadata.
- https://sansad.in/api_rs/member/bio-data?mpCode=2590&locale=en — biography example.
- https://sansad.in/api_rs/member/position-held?mpCode=2590&locale=en — positions example.
- https://sansad.in/rs/members/biographyM/2590 — public profile example.

## Matching and boundaries

Honorifics, punctuation and official surname-first aliases are normalized.
Matching requires exactly one identity; initials are not reordered or expanded.
Separate `profile_house` namespaces prevent overlapping numeric member IDs from
returning the wrong House's portrait or biography.

Questioners and debate participants in RS use the RS directory. Explicitly named
answering ministers and LS bill presenters may be members of the other House;
an exact, unique second-directory lookup is allowed for these roles. A minister
is never inferred solely from the ministry. Debate catalogue participation does
not prove who spoke or voted. Source names survive unsuccessful identity matches.

Some former-member biographies/portraits may be missing or temporarily unavailable.
The card keeps its source name/link and gives a fallback message. Party/state and
positions reflect the fetched profile, not necessarily the historical event date.
Source data is cached using the existing 24-hour cache/stale-source fallback.

New API: `GET /api/rs-profiles/{member_id}` and
`GET /api/rs-profile-photo/{member_id}`. Portrait fetching accepts HTTPS official
RS portrait paths only, validates redirects, limits size and checks image type.

## Verification

- Full available test suite: 134 passed, 2 pre-existing source-file checks skipped.
- JavaScript syntax check passed.
- Live RS debate `RS_D_746171`: Bhim Singh, RS ID 2590; portrait HTTP 200 JPEG;
  browser confirmed portrait, education and career timeline.
- Live RS QA `RS_267_313792`: Vaiko, RS ID 728; absent explicit minister heading
  correctly remains unidentified.
- Historical QA `RS_K_6ed168f17b0b61cca5ce1251`: R.C. Singh, RS ID 2088;
  explicit answering minister E. Ahamed, LS ID 10.
- Telecommunications Bill `B_b591e262b9cf92da03573c6b`: Ashwini Vaishnaw,
  RS ID 2425, with the existing verified introduction role.
- Existing LS Pratima Mondal debate remains matched to LS ID 4871.

The app was restarted with its persistent data retained. Background speech
indexing was paused before restart and resumed afterwards.
