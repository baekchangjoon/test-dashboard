Feature: Access control on protected API endpoints

  Scenario Outline: Anonymous requests to protected endpoints are refused
    When an anonymous client sends a <method> request to "<path>"
    Then the access control response is unauthorized or forbidden

    Examples:
      | method | path                  |
      | GET    | /api/reservations     |
      | GET    | /api/reservations/1   |
      | GET    | /api/owners           |
      | POST   | /api/owners           |

  Scenario: A request with an invalid bearer token is refused
    When a client with an invalid bearer token lists the reservations
    Then the access control response is unauthorized or forbidden
