targetScope = 'subscription'

@description('Budget resource name.')
param budgetName string

@description('Resource group whose costs are included in this budget.')
param resourceGroupName string

@minValue(1)
@description('Monthly amount in the subscription billing currency.')
param amount int

@minLength(1)
@description('Budget notification recipients.')
param contactEmails array

@description('First day of the budget period in UTC.')
param startDate string

resource budget 'Microsoft.Consumption/budgets@2024-08-01' = {
  name: budgetName
  properties: {
    amount: amount
    category: 'Cost'
    filter: {
      dimensions: {
        name: 'ResourceGroupName'
        operator: 'In'
        values: [
          resourceGroupName
        ]
      }
    }
    notifications: {
      Actual_GreaterThanOrEqualTo_50_Percent: {
        contactEmails: contactEmails
        contactGroups: []
        contactRoles: []
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 50
        thresholdType: 'Actual'
      }
      Actual_GreaterThanOrEqualTo_80_Percent: {
        contactEmails: contactEmails
        contactGroups: []
        contactRoles: []
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 80
        thresholdType: 'Actual'
      }
      Actual_GreaterThanOrEqualTo_100_Percent: {
        contactEmails: contactEmails
        contactGroups: []
        contactRoles: []
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 100
        thresholdType: 'Actual'
      }
      Forecast_GreaterThanOrEqualTo_100_Percent: {
        contactEmails: contactEmails
        contactGroups: []
        contactRoles: []
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 100
        thresholdType: 'Forecasted'
      }
    }
    timeGrain: 'Monthly'
    timePeriod: {
      startDate: startDate
    }
  }
}
