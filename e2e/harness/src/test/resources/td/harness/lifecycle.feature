Feature: Lifecycle sample

  Scenario: plain hit
    When the sample server is pinged

  Scenario Outline: row <n>
    When the sample server is pinged
    Then nothing else happens <n>

    Examples:
      | n |
      | 1 |
      | 2 |

  Scenario: no requests
    Then nothing else happens 0

  Scenario: undefined
    Given a step nobody defined
