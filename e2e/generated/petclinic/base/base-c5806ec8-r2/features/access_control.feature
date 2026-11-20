Feature: Access control for protected API endpoints

  Scenario Outline: Anonymous callers cannot read protected resources
    When an anonymous caller requests "<path>"
    Then the anonymous request is refused as unauthenticated

    Examples:
      | path              |
      | /api/owners       |
      | /api/reservations |

  Scenario: Anonymous callers cannot create reservations
    When an anonymous caller submits a new reservation
    Then the anonymous request is refused as unauthenticated
