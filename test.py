
import ast
import re
from pathlib import Path


ROOT = Path.cwd()

STORAGE = ROOT / "src" / "storage.py"
SCHEDULER = ROOT / "scheduler.py"
APP = ROOT / "app.py"
CREDIT = ROOT / "src" / "Russia" / "credit.py"


CREDIT_TAB_CODE = '''
        with credit_tab:
            st.subheader("Задолженность по кредитам")

            st.caption(
                "Банк России · млрд рублей · "
                "на первое число месяца · с января 2024 года"
            )

            credit_data = load_russia_credit()

            credit_labels = {
                "personal_debt": "Задолженность физических лиц",
                "company_debt": "Задолженность компаний и ИП",
                "sme_debt": "Задолженность МСП",
            }

            if credit_data.empty:
                st.warning(
                    "Данные отсутствуют. "
                    "Запусти python scheduler.py ru."
                )
            else:
                credit_data = credit_data.loc[
                    credit_data["country"] == "RU"
                ].copy()

                credit_data["date"] = pd.to_datetime(
                    credit_data["date"]
                )

                credit_data = credit_data.loc[
                    credit_data["date"] >= "2024-01-01"
                ].sort_values("date")

                available = {
                    key: label
                    for key, label in credit_labels.items()
                    if (
                        key in credit_data.columns
                        and credit_data[key].notna().any()
                    )
                }

                if available:
                    selected = st.multiselect(
                        "Показатели для сравнения",
                        options=list(available),
                        default=list(available),
                        format_func=lambda key: available[key],
                        key="ru_credit_selected",
                    )

                    if selected:
                        ru_line_chart(
                            credit_data,
                            "Кредитная задолженность России",
                            {
                                key: available[key]
                                for key in selected
                            },
                            unit="млрд ₽",
                        )
                    else:
                        st.info(
                            "Выбери хотя бы один показатель."
                        )

                    latest = []

                    for key, label in available.items():
                        valid = (
                            credit_data[["date", key]]
                            .dropna(subset=[key])
                            .sort_values("date")
                        )

                        if valid.empty:
                            continue

                        row = valid.iloc[-1]

                        latest.append({
                            "Показатель": label,
                            "Дата": row["date"].strftime(
                                "%d.%m.%Y"
                            ),
                            "Задолженность, млрд ₽": round(
                                float(row[key]), 3
                            ),
                        })

                    if latest:
                        st.subheader(
                            "Последние опубликованные значения"
                        )

                        st.dataframe(
                            pd.DataFrame(latest),
                            hide_index=True,
                            use_container_width=True,
                        )
                else:
                    st.warning(
                        "В таблице нет доступных показателей."
                    )

            st.caption(
                "Источник: Банк России. "
                "Задолженность физических лиц, "
                "юридических лиц и ИП, субъектов МСП. "
                "Категории пересекаются, поэтому "
                "складывать их значения нельзя."
            )

'''


def has_import(tree, module, name):
    return any(
        isinstance(node, ast.ImportFrom)
        and node.module == module
        and any(
            alias.name == name
            for alias in node.names
        )
        for node in ast.walk(tree)
    )


def patch_storage(source):
    tree = ast.parse(source)

    tables = None

    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(
                isinstance(target, ast.Name)
                and target.id == "STANDARD_TABLES"
                for target in node.targets
            ):
                tables = node.value
                break

    if not isinstance(tables, ast.Dict):
        raise RuntimeError(
            "storage.py: не найден STANDARD_TABLES"
        )

    names = [
        key.value
        for key in tables.keys
        if isinstance(key, ast.Constant)
        and isinstance(key.value, str)
    ]

    lines = source.splitlines(keepends=True)

    if "russia_credit" not in names:
        if "russia_rates" not in names:
            raise RuntimeError(
                "storage.py: отсутствует russia_rates"
            )

        target_line = None

        for key in tables.keys:
            if (
                isinstance(key, ast.Constant)
                and key.value == "russia_rates"
            ):
                target_line = key.lineno
                break

        lines.insert(
            target_line - 1,
            '    "russia_credit": "date",\n',
        )

        source = "".join(lines)

    # Добавляем новую таблицу также в clear_all().
    tree = ast.parse(source)

    if not any(
        isinstance(node, ast.FunctionDef)
        and node.name == "clear_all"
        for node in tree.body
    ):
        raise RuntimeError(
            "storage.py: не найдена clear_all"
        )

    clear_function = next(
        node
        for node in tree.body
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == "clear_all"
        )
    )

    clear_text = "\n".join(
        source.splitlines()[
            clear_function.lineno - 1:
            clear_function.end_lineno
        ]
    )

    if '"russia_credit"' not in clear_text:
        pattern = r'("russia_quarterly"\s*,)'

        if not re.search(pattern, clear_text):
            raise RuntimeError(
                "storage.py: в clear_all не найдена "
                "russia_quarterly"
            )

        replacement = re.sub(
            pattern,
            r'\\g<1> "russia_credit",',
            clear_text,
            count=1,
        )

        lines = source.splitlines(keepends=True)

        start = clear_function.lineno - 1
        end = clear_function.end_lineno

        lines[start:end] = [
            line + "\n"
            for line in replacement.splitlines()
        ]

        source = "".join(lines)

    return source


def patch_scheduler(source):
    tree = ast.parse(source)

    imports = []

    if not has_import(
        tree,
        "src.Russia.credit",
        "fetch_russia_credit",
    ):
        imports.append(
            "from src.Russia.credit "
            "import fetch_russia_credit"
        )

    if not has_import(
        tree,
        "src.storage",
        "save_russia_credit",
    ):
        imports.append(
            "from src.storage "
            "import save_russia_credit"
        )

    if imports:
        lines = source.splitlines(keepends=True)

        # Импорты размещаем прямо перед функцией _step.
        step_function = next(
            (
                node for node in tree.body
                if isinstance(node, ast.FunctionDef)
                and node.name == "_step"
            ),
            None,
        )

        if step_function is None:
            raise RuntimeError(
                "scheduler.py: не найдена _step"
            )

        lines.insert(
            step_function.lineno - 1,
            "\n".join(imports) + "\n\n",
        )

        source = "".join(lines)

    tree = ast.parse(source)

    groups = next(
        (
            node.value
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name)
                and target.id == "GROUPS"
                for target in node.targets
            )
        ),
        None,
    )

    if not isinstance(groups, ast.Dict):
        raise RuntimeError(
            "scheduler.py: не найден GROUPS"
        )

    ru_steps = None

    for key, value in zip(
        groups.keys,
        groups.values,
    ):
        if (
            isinstance(key, ast.Constant)
            and key.value == "ru"
        ):
            ru_steps = value
            break

    if not isinstance(ru_steps, ast.List):
        raise RuntimeError(
            "scheduler.py: не найдена группа ru"
        )

    already_added = any(
        isinstance(node, ast.Name)
        and node.id == "fetch_russia_credit"
        for node in ast.walk(ru_steps)
    )

    if not already_added:
        lines = source.splitlines(keepends=True)

        # Закрывающая строка списка группы ru.
        closing_line = ru_steps.end_lineno

        addition = (
            '        (\n'
            '            "Россия: задолженность физлиц, "\n'
            '            "компаний и МСП (ЦБ РФ)",\n'
            '            fetch_russia_credit,\n'
            '            save_russia_credit,\n'
            '        ),\n'
        )

        lines.insert(
            closing_line - 1,
            addition,
        )

        source = "".join(lines)

    return source


def find_country_tabs(tree):
    """
    Находит st.tabs(...) для детальной страницы
    России по имени переменной other_tab.
    """

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue

        if not isinstance(node.value, ast.Call):
            continue

        call = node.value

        if not (
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "tabs"
        ):
            continue

        if not (
            isinstance(call.func.value, ast.Name)
            and call.func.value.id == "st"
        ):
            continue

        if len(node.targets) != 1:
            continue

        target = node.targets[0]

        if not isinstance(
            target,
            (ast.Tuple, ast.List),
        ):
            continue

        names = [
            element.id
            for element in target.elts
            if isinstance(element, ast.Name)
        ]

        if (
            "other_tab" in names
            and "rates_tab" in names
        ):
            return node, names

    return None, None


def patch_app(source):
    tree = ast.parse(source)

    if not has_import(
        tree,
        "src.storage",
        "load_russia_credit",
    ):
        # Отдельный импорт: не зависит от
        # форматирования существующих импортов.
        lines = source.splitlines(keepends=True)

        streamlit_import = next(
            (
                node
                for node in tree.body
                if isinstance(node, ast.Import)
                and any(
                    alias.name == "streamlit"
                    for alias in node.names
                )
            ),
            None,
        )

        if streamlit_import is None:
            raise RuntimeError(
                "app.py: не найден импорт streamlit"
            )

        lines.insert(
            streamlit_import.end_lineno,
            "from src.storage "
            "import load_russia_credit\n",
        )

        source = "".join(lines)

    tree = ast.parse(source)

    tabs_node, names = find_country_tabs(tree)

    if tabs_node is None:
        raise RuntimeError(
            "app.py: не удалось найти вкладки "
            "детальной страницы России"
        )

    if "credit_tab" not in names:
        if (
            not tabs_node.value.args
            or not isinstance(
                tabs_node.value.args[0],
                (ast.List, ast.Tuple),
            )
        ):
            raise RuntimeError(
                "app.py: список названий вкладок "
                "имеет неизвестную структуру"
            )

        labels = ast.literal_eval(
            tabs_node.value.args[0]
        )

        if len(labels) != len(names):
            raise RuntimeError(
                "app.py: число вкладок "
                "не совпадает с их названиями"
            )

        position = names.index("other_tab")

        names.insert(
            position,
            "credit_tab",
        )

        labels.insert(
            position,
            "Кредитование",
        )

        indent = " " * tabs_node.col_offset

        new_assignment = (
            indent
            + "("
            + ", ".join(names)
            + ") = st.tabs(\n"
            + indent
            + "    "
            + repr(labels)
            + "\n"
            + indent
            + ")\n"
        )

        lines = source.splitlines(keepends=True)

        lines[
            tabs_node.lineno - 1:
            tabs_node.end_lineno
        ] = [new_assignment]

        source = "".join(lines)

    if "with credit_tab:" not in source:
        tree = ast.parse(source)

        other_with = next(
            (
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.With)
                and any(
                    isinstance(item.context_expr, ast.Name)
                    and item.context_expr.id == "other_tab"
                    for item in node.items
                )
            ),
            None,
        )

        if other_with is None:
            raise RuntimeError(
                "app.py: не найдена вкладка other_tab"
            )

        if other_with.col_offset != 8:
            raise RuntimeError(
                "app.py: неожиданная вложенность "
                "вкладки other_tab"
            )

        lines = source.splitlines(keepends=True)

        lines.insert(
            other_with.lineno - 1,
            CREDIT_TAB_CODE.lstrip("\n"),
        )

        source = "".join(lines)

    return source


def main():
    required = (
        STORAGE,
        SCHEDULER,
        APP,
        CREDIT,
    )

    for path in required:
        if not path.is_file():
            raise FileNotFoundError(
                f"Файл не найден: {path}"
            )

    originals = {
        path: path.read_text(
            encoding="utf-8-sig"
        )
        for path in (STORAGE, SCHEDULER, APP)
    }

    # Формируем ВСЕ изменения в памяти.
    updated = {
        STORAGE: patch_storage(
            originals[STORAGE]
        ),
        SCHEDULER: patch_scheduler(
            originals[SCHEDULER]
        ),
        APP: patch_app(
            originals[APP]
        ),
    }

    # Проверяем синтаксис до записи.
    for path, code in updated.items():
        compile(code, str(path), "exec")

    # Проверяем возможность найти новую группу
    # и зарегистрированную таблицу.
    storage_tree = ast.parse(updated[STORAGE])
    scheduler_tree = ast.parse(updated[SCHEDULER])

    assert has_import(
        scheduler_tree,
        "src.Russia.credit",
        "fetch_russia_credit",
    )

    assert has_import(
        scheduler_tree,
        "src.storage",
        "save_russia_credit",
    )

    assert "russia_credit" in updated[STORAGE]
    assert "with credit_tab:" in updated[APP]

    print(
        "[OK] Все изменения прошли "
        "синтаксическую проверку"
    )

    for path, code in updated.items():
        if code == originals[path]:
            print("[SKIP]", path.name)
            continue

        path.write_text(
            code,
            encoding="utf-8",
        )

        print("[OK]", path.name)

    print()
    print("[OK] Интеграция кредитования завершена")
    print("[OK] Новые .bak не создавались")
    print("[OK] SQLite ещё не изменялась")


if __name__ == "__main__":
    main()
