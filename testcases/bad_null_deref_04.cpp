/* CWE-476: Null Pointer Dereference via arrow member access (BAD)
 * C++ idiom: nullptr struct pointer, accessed with `->`.
 * Expected detection: null_deref
 */
struct Widget {
    int value;
};

int main() {
    Widget* w = nullptr;
    w->value = 1;       /* <-- arrow deref of nullptr */
    return 0;
}
