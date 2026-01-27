# Architectural Decisions - separate-image-div

## Parser Choice
- **Decision**: Use regex-based parsing (not BeautifulSoup)
- **Rationale**: Maintain consistency with existing codebase patterns

## Processing Scope
- **Decision**: Only direct children of top-level div
- **Rationale**: Avoid complexity of nested structures

## Text Node Handling
- **Decision**: Wrap text nodes in separate divs
- **Rationale**: User requirement for consistency
