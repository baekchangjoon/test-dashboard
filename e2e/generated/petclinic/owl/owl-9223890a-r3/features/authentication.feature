Feature: Authentication and access control
  The API requires a bearer token and exposes login and token validation endpoints.

  Scenario: Login with an unknown username is rejected
    When a login is attempted with a random unknown username
    Then the authentication response is a client error

  Scenario: Login with blank credentials is rejected
    When a login is attempted with blank credentials
    Then the authentication response is a client error

  Scenario: The token of the current session is accepted by the validation endpoint
    When the current harness session token is validated
    Then the authentication response is successful

  Scenario Outline: Anonymous access to a protected endpoint is denied
    When an anonymous client sends GET "<path>"
    Then access to the protected endpoint is denied with status 401 or 403

    Examples:
      | path              |
      | /api/owners       |
      | /api/vets         |
      | /api/reservations |
      | /api/pets/types   |

  Scenario: A forged bearer token is rejected
    When a client sends GET "/api/owners" with a forged bearer token
    Then access to the protected endpoint is denied with status 401 or 403
