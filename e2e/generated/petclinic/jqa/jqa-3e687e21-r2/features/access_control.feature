Feature: API access control and authentication
  Protected endpoints require a valid bearer token and the auth endpoints reject bad input.

  Scenario Outline: Anonymous read of <path> is denied
    When an anonymous client sends GET to "<path>"
    Then the access control response status is 401 or 403

    Examples:
      | path              |
      | /api/owners       |
      | /api/reservations |

  Scenario: Anonymous reservation creation is denied
    When an anonymous client submits a boarding reservation
    Then the access control response status is 401 or 403

  Scenario: A malformed bearer token is rejected
    When a client presenting the malformed bearer token "not-a-real-token" sends GET to "/api/owners"
    Then the access control response status is 401 or 403

  Scenario: Login with an unknown username and password fails
    When an anonymous client logs in with a random unknown username and password
    Then the login attempt is rejected with a client error

  Scenario: Login with an empty body fails
    When an anonymous client posts an empty login body
    Then the login attempt is rejected with a client error

  Scenario: Validating a garbage token does not cause a server error
    When an anonymous client asks to validate the garbage token "garbage.token.value"
    Then the token validation does not fail with a server error
