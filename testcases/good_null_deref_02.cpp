/* CWE-476: Null Pointer Dereference (GOOD / true negative)
 * Pointer starts as nullptr but is reassigned to a valid address before use.
 * Expected detection: none
 */
int main() {
    int x = 42;
    int* p = nullptr;
    p = &x;             /* reassigned to a valid object */
    *p = 5;
    return 0;
}
