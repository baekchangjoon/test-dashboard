Feature: POST /api/auth/login
  Deterministic cases derived from the analysis inputs for one endpoint.

  Background:
    Given the SUT timezone is "Asia/Seoul"

  @case:loaduserbyusername-violation-1
  Scenario: loaduserbyusername-violation-1
    Given the case "loaduserbyusername-violation-1"
    And a request to "POST /api/auth/login"
    And body field "password" is "uniq:loaduserbyusername-violation-1"
    And body field "username" is "user"
    When the request is sent
    Then the response status is 404
