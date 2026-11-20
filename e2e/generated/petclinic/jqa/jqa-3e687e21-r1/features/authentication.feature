Feature: Authentication and access control

  Scenario: Logging in with an unknown username is rejected
    When the client logs in with an unknown username and a random password
    Then the login attempt is rejected with a client error

  Scenario: Logging in as admin with a wrong password is rejected
    When the client logs in as "admin" with a random wrong password
    Then the login attempt is rejected with a client error

  Scenario Outline: Anonymous read access to a protected API is denied
    When an anonymous client sends GET to "<path>"
    Then the anonymous request is denied

    Examples:
      | path              |
      | /api/owners       |
      | /api/reservations |

  Scenario: Anonymous creation of a reservation is denied
    When an anonymous client submits a boarding reservation
    Then the anonymous request is denied
