Feature: Access control for protected API endpoints
  Requests without valid authentication are rejected.

  Scenario Outline: Anonymous callers cannot read protected resources
    When an anonymous client sends a GET request to "<path>"
    Then the unauthenticated call is rejected with status 401 or 403

    Examples:
      | path              |
      | /api/reservations |
      | /api/owners       |

  Scenario: A forged bearer token is rejected
    When a client with a forged bearer token sends a GET request to "/api/owners"
    Then the unauthenticated call is rejected with status 401 or 403
