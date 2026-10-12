# Skriller design system

Proposed implementation direction, derived under the user's instruction to proceed autonomously. Branding is not user-approved.

## World

A quiet research reading desk: warm paper, pale sage navigation, deep green actions, strong text hierarchy and ruled evidence lists. Dense results should inherit the same vocabulary; no decorative metrics or invented data.

## Tokens

- Ink: `#23342d`; muted text: `#596a60`.
- Main surface: `#fcfcf8`; secondary surface: `#f2f4ed`.
- Border: `#d8dfd5`; primary action: `#245943`; focus: `#357952`.
- Error text: `#8b3029` on `#fcf0eb`.
- UI typography: Arial/Helvetica system sans, 14px body, 12px controls, 34px desktop heading. Product labels use the same family.
- Composer radius: 14px; buttons: 8px; spacing: 4/8/12/16/20/24/32/48/64px.

## Structure

246px navigation at desktop, a restrained service-status header, a centred prompt workspace and a source-evidence empty state. Below 760px navigation becomes a compact top bar; the composer stays first and source controls wrap.

## Interaction

Prompt is the primary control. Examples populate it, never run automatically. Source selection and result limits are optional. Readiness is obtained from the API. Offline, setup, authentication and request failures are explicit; input survives failures. No fake conversations or prospects.

## Accessibility

Visible keyboard focus, skip link, semantic form labels, status/alert announcements and reduced-motion support. Source controls use native checkboxes and result control uses a native select.

## Direction process

Grounded candidates: 1 research notebook, 2 professional directory, 3 newsroom assignment desk, 4 library catalogue, 5 research reading desk, 6 project operations board, 7 analyst spreadsheet. Design seed assigned candidate 5. Challengers were evaluated for professional audience identification and prompt/evidence clarity; strongly theatrical media, navigation and barcode directions did not improve either. Their useful discipline is retained as clarity of state and deliberate information density, without decorative imitation. This proposed direction can be revised with future user feedback; no standing workflow preference was recorded.
