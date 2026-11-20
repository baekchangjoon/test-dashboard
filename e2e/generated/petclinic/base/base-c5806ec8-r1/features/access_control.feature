Feature: Access control for protected endpoints
  Requests without an Authorization header are refused.

  Scenario Outline: Anonymous requests to protected endpoints are refused
    When an anonymous client sends <method> to <path>
    Then the anonymous request is refused as unauthenticated

    Examples:
      | method | path              |
      | GET    | /api/reservations |
      | POST   | /api/reservations |
      | GET    | /api/owners       |
