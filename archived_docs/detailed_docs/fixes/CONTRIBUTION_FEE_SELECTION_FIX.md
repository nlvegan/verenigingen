# Custom Contribution Fee Selection Fix

## Issues Identified and Fixed

### 1. **Primary Issue - Incorrect Selector for "Choose Amount" Option**
**Problem**: The `applyCalculatedAmount` function was looking for an input with `name="membership_type_selection"` to find the "Choose amount" option, but the actual implementation uses a button with class `toggle-custom`.

**Root Cause**:
```javascript
// OLD - Incorrect selector
const customOption = $('input[name="membership_type_selection"][value*="custom"], input[name="membership_type_selection"][value*="choose"]');
```

The actual "Choose Amount" functionality is implemented via:
- Button with class `toggle-custom` (from `createMembershipCard` function)
- Custom amount input with class `custom-amount-input`
- Custom amount section with class `custom-amount-section`

### 2. **Membership Type Selection Logic**
**Problem**: The code was calling `membershipCard.click()` which clicked the entire card instead of the specific "Select" button.

**Fix**: Now properly clicks the `.select-membership` button first.

### 3. **Billing Interval Detection**
**Problem**: Limited debugging information to understand why membership types weren't being matched.

**Fix**: Added comprehensive logging to track membership type availability and matching.

## Detailed Fixes Implemented

### 1. **Enhanced `applyCalculatedAmount` Function**

**File**: `verenigingen/public/js/membership_application.js`

**Key Changes**:

1. **Proper Membership Type Selection**:
   ```javascript
   // Now clicks the actual Select button
   const selectButton = membershipCard.find('.select-membership');
   if (selectButton.length) {
       selectButton.click();
   }
   ```

2. **Correct "Choose Amount" Button Detection**:
   ```javascript
   // Look for the actual "Choose Amount" button
   const chooseAmountButton = membershipCard.find('.toggle-custom');
   if (chooseAmountButton.length) {
       chooseAmountButton.click(); // Show custom amount section
   }
   ```

3. **Proper Custom Amount Input Handling**:
   ```javascript
   // Set the amount in the correct custom input field
   const customInput = membershipCard.find('.custom-amount-input');
   if (customInput.length) {
       customInput.val(amount.toFixed(2)).trigger('input');
       // Trigger proper selection with custom amount
       this.selectMembershipType(membershipCard, true, amount);
   }
   ```

4. **Enhanced Fallback Logic**:
   ```javascript
   // Fallback: Try first membership type with custom amount support
   const firstCardWithCustom = $('.membership-type-card').filter((index, card) => {
       return $(card).find('.toggle-custom').length > 0;
   }).first();
   ```

### 2. **Improved Debugging and Logging**

Added comprehensive console logging to track:
- Membership type detection
- Button clicking actions
- Input field availability
- Amount setting operations

**Example Logging**:
```javascript
console.log('Found membership card:', membershipCard.length > 0, 'for type:', targetMembershipType.name);
console.log('Found choose amount button:', chooseAmountButton.length > 0);
console.log('Found custom input:', customInput.length > 0);
console.log('Set custom amount:', amount.toFixed(2));
```

### 3. **Enhanced Timing and Sequencing**

**Improved Timing**:
- Increased timeouts to allow proper DOM updates
- Sequential execution: Select → Choose Amount → Set Value → Trigger Selection

**Timing Sequence**:
1. Click membership type select button
2. Wait 400ms for selection to process
3. Click "Choose Amount" button
4. Wait 300ms for custom section to appear
5. Set custom amount and trigger selection

### 4. **Robust Error Handling**

**Multiple Fallback Levels**:
1. Primary: Find matching membership type by payment interval
2. Secondary: Use any membership type with custom amount support
3. Tertiary: Show user message to manually select

**Graceful Degradation**:
- If specific elements aren't found, try alternative approaches
- Always provide user feedback about what happened
- Never fail silently

## Technical Implementation Details

### How "Choose Amount" Actually Works

1. **Button Structure** (from `createMembershipCard`):
   ```javascript
   // Standard button
   '<button type="button" class="btn btn-primary select-membership">Select</button>'

   // Custom amount button (only if allow_custom_amount is true)
   '<button type="button" class="btn btn-outline-secondary toggle-custom">Choose Amount</button>'
   ```

2. **Event Binding** (from `bindMembershipEvents`):
   ```javascript
   $('.toggle-custom').on('click', (e) => {
       const customSection = card.find('.custom-amount-section');
       if (customSection.is(':visible')) {
           customSection.hide(); // Hide custom section
           button.text('Choose Amount');
       } else {
           customSection.show(); // Show custom section
           button.text('Standard Amount');
       }
   });
   ```

3. **Custom Amount Input**:
   ```javascript
   '<input type="number" class="form-control custom-amount-input"
          min="' + minAmount + '" step="0.01" placeholder="Enter amount">'
   ```

### Billing Interval Matching Logic

**Enhanced Detection** with logging:
```javascript
const intervalMatchers = {
    'monthly': ['month', 'maand', 'monthly'],
    'quarterly': ['quarter', 'kwartaal', 'quarterly', 'driemaandelijk'],
    'annually': ['year', 'jaar', 'annual', 'yearly', 'jaarlijks']
};
```

**Matching Process**:
1. Get payment interval from `#calc-payment-interval` dropdown
2. Look through available membership types
3. Match interval keywords in membership type names/descriptions
4. Return first matching type

## Testing Verification

### Test Scenarios

1. **Monthly Payment Interval**:
   - Should find membership type containing "month" or "monthly"
   - Should click "Choose Amount" button
   - Should set calculated amount

2. **Quarterly Payment Interval**:
   - Should find membership type containing "quarter" or "quarterly"
   - Should apply 3-month calculation

3. **Annual Payment Interval**:
   - Should find membership type containing "year" or "annual"
   - Should apply 12-month calculation

4. **No Matching Type**:
   - Should use first available type with custom amount support
   - Should show appropriate user message

### Console Debugging

When testing, check browser console for:
```
Finding membership type for interval: monthly
Available membership types: 3 [array of types]
Found membership card: true for type: Monthly Membership
Clicked select button for membership type: Monthly Membership
Found choose amount button: true
Clicked choose amount button
Found custom input: true
Set custom amount: 35.00
```

## User Experience Improvements

1. **Automatic Selection**: Calculator now automatically selects appropriate membership type
2. **Visual Feedback**: Shows custom amount section automatically
3. **Clear Messaging**: Provides feedback about what action was taken
4. **Smooth Scrolling**: Automatically scrolls to membership selection area
5. **Robust Fallbacks**: Always tries to help user even if matching fails

## Files Modified

- **`verenigingen/public/js/membership_application.js`**:
  - Fixed `applyCalculatedAmount` function
  - Enhanced `findMembershipTypeByInterval` function
  - Improved error handling and logging

The custom contribution fee selection should now work correctly, properly detecting billing intervals, finding matching membership types, and automatically selecting the "Choose Amount" option with the calculated contribution amount.
