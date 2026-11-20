Feature: Access control on protected API endpoints

  Scenario Outline: Anonymous <method> request to <path> is denied
    When an anonymous client sends <method> to "<path>"
    Then the anonymous request is denied

    Examples:
      | method | path              |
      | GET    | /api/reservations |
      | POST   | /api/reservations |
      | GET    | /api/owners       |
      | GET    | /api/vets         |
